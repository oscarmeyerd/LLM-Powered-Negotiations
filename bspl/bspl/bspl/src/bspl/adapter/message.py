#!/usr/bin/env python3

import agentspeak
from agentspeak import Literal, Var
import re
from ..utils import camel_to_snake


def get_key(schema, payload):
    # schema.keys should be ordered, or sorted for consistency
    return ",".join(k + ":" + str(payload[k]) for k in schema.keys)


class Message:
    schema = None
    payload = {}
    acknowledged = False
    _dest = None
    _dests = None
    adapter = None
    meta = {}
    key = None

    def __init__(
        self,
        schema,
        payload=None,
        meta={},
        acknowledged=False,
        dest=None,
        adapter=None,
        system=None,
    ):
        self.schema = schema
        self.payload = payload or {}
        self.acknowledged = acknowledged
        self._dest = dest  # Use private attribute for backwards compatibility
        self._dests = None  # Initialize multiple destinations
        self.adapter = adapter
        self.meta = {"system": system, **meta}

    @property
    def key(self):
        return get_key(self.schema, self.payload)

    @property
    def system(self):
        return self.meta["system"]

    @property
    def recipients(self):
        s = self.adapter.systems[self.system]
        return [s["roles"][r] for r in self.schema.recipients]

    @property
    def recipient(self):
        """Single recipient role - convenience for single recipient case"""
        recipients = self.recipients
        return recipients[0] if recipients else None

    @property
    def dests(self):
        """List of destination endpoints - can be set as override"""
        if self._dests is not None:
            return self._dests
        elif self._dest is not None:
            return [self._dest]
        else:
            return []

    @dests.setter
    def dests(self, value):
        """Set multiple destination endpoints - clears dest"""
        if value is not None:
            if not isinstance(value, list):
                raise ValueError("dests must be a list of (host, port) tuples")
            for endpoint in value:
                if not (isinstance(endpoint, tuple) and len(endpoint) == 2):
                    raise ValueError(f"Invalid endpoint {endpoint}: must be (host, port) tuple")
                host, port = endpoint
                if not isinstance(host, str) or not isinstance(port, int):
                    raise ValueError(f"Invalid endpoint {endpoint}: host must be string, port must be int")
        self._dests = value
        self._dest = None  # Clear single dest when setting multiple

    @property
    def dest(self):
        """Single destination endpoint - convenience for single recipient case"""
        dests = self.dests
        return dests[0] if dests else self._dest

    @dest.setter
    def dest(self, value):
        """Set single destination endpoint - clears dests"""
        if value is not None:
            if not (isinstance(value, tuple) and len(value) == 2):
                raise ValueError(f"Invalid endpoint {value}: must be (host, port) tuple")
            host, port = value
            if not isinstance(host, str) or not isinstance(port, int):
                raise ValueError(f"Invalid endpoint {value}: host must be string, port must be int")
        self._dest = value
        self._dests = None  # Clear multiple dests when setting single

    def __repr__(self):
        payload = ",".join("{0}={1!r}".format(k, v) for k, v in self.payload.items())
        meta = ",".join("{0}={1!r}".format(k, v) for k, v in self.meta.items())
        return f"{self.schema.name}({payload}){{{meta}}}"

    def __eq__(self, other):
        return (
            self.payload == other.payload
            and self.schema == other.schema
            and self.system == other.system
        )

    def __hash__(self):
        return hash(self.schema.qualified_name + self.key)

    def __getitem__(self, name):
        return self.payload[name]

    def __setitem__(self, name, value):
        if name not in self.schema.parameters:
            raise Exception(f"Parameter {name} is not in schema {self.schema}")
        adornment = self.schema.parameters[name].adornment
        if adornment == "out":
            self.payload[name] = value
            return value
        else:
            raise Exception(f"Parameter {name} is {adornment}, not out")

    def bind(self, **kwargs):
        for k, v in kwargs.items():
            self[k] = v
        return self

    def instance(self, **kwargs):
        """
        Return new instance of message, binding new parameters from kwargs
        """
        return self.schema(**self.payload).bind(**kwargs)

    def keys_match(self, other):
        return all(
            self.payload[k] == other.payload[k]
            for k in self.schema.keys
            if k in other.schema.parameters
        )

    def keys(self):
        return self.payload.keys()

    def project_key(self, schema):
        """Give the subset of this instance's keys that match the provided schema, in the order of the provided schema"""
        key = {}
        # use ordering from other schema
        for k in schema.keys:
            if k in self.schema.keys:
                key[k] = self[k]
        return key

    def send(self):
        self.adapter.send(self)

    def context(self, schema=None):
        return self.adapter.history.context(self, schema)

    def term(self):
        functor = camel_to_snake(self.schema.name)
        parameters = self.schema.order_params(self.payload, default=agentspeak.Var)

        return Literal(
            functor,
            (
                self.system,
                self.schema.sender.name,
                *[r.name for r in self.schema.recipients],
                *parameters,
            ),
        )

    def enabled_term(self):
        parameters = self.schema.order_params(self.payload, default=None)
        msg = Literal(
            camel_to_snake(self.schema.name),
            (
                self.system,
                self.schema.sender.name,
                *[r.name for r in self.schema.recipients],
                *parameters,
            ),
        )
        return Literal("enabled", (msg,))

    def resolve(self, term, scope, memo={}):
        system = term.args[0]
        sender = term.args[1]
        # Extract recipients (number determined by schema)
        num_recipients = len(self.schema.recipients)
        recipients = term.args[2:2+num_recipients]
        # Parameters start after all recipients
        payload = self.schema.zip_params(*term.args[2+num_recipients:])
        for p, v in payload.items():
            if isinstance(v, agentspeak.Var):
                val = agentspeak.deref(memo.get(v, v), scope)
                if (
                    isinstance(val, agentspeak.Var)
                    and self.schema.parameters[p].adornment == "out"
                ):
                    return False
                payload[p] = val
        return Message(self.schema, payload, system=system)

    @property
    def complete(self):
        # payload must contain something other than None for all ins and outs
        return all(
            self.payload.get(k) != None for k in self.schema.ins.union(self.schema.outs)
        )

    def partial(self):
        return Partial(self)

    def serialize(self):
        return {"schema": self.schema.qualified_name, "payload": self.payload, "meta": self.meta}


class Partial(Message):
    def __init__(self, message):
        self.schema = message.schema
        self.adapter = message.adapter
        # the base bindings that are used to initialize each instance
        self.bindings = self.payload = message.payload.copy()
        self._dest = None

        self.instances = []
        self.meta = message.meta.copy()

    def bind(self, **kwargs):
        inst = Message(
            self.schema, self.bindings.copy(), dest=self._dest, system=self.system
        )
        for k, v in kwargs.items():
            inst[k] = v
        if not inst.complete:
            raise Exception(f"Bind must produce a complete instance: {inst}")
        self.instances.append(inst)
        return inst
