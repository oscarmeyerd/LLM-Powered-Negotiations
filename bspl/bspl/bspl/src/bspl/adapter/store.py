import logging
import itertools
import types
from .message import Message

logger = logging.getLogger("bspl.store")
logger.setLevel(logging.DEBUG)


def check(p, test):
    if type(test) == types.FunctionType:
        return test(p)
    else:
        return p == test


class Context:
    def __init__(self, parent=None):
        self.subcontexts = {}
        self._bindings = {}
        self._messages = {}
        self.parent = parent

    def add(self, message):
        self._bindings.update(message.payload)
        self._messages[message.schema] = message

    def clear(self):
        """Remove all content of the context"""
        self.__init__(self.parent)

    @property
    def bindings(self):
        """Return all parameters bound directly in this context or its ancestors"""
        # may not be efficient enough, since it collects all of the
        # bindings every time it's accessed
        if self.parent:
            return {**self.parent.bindings, **self._bindings}
        else:
            return self._bindings.copy()

    def _all_bindings(self):
        """
        Return all bindings declared within a context - including its subcontexts
        """
        bs = {}
        for p in self.subcontexts:
            bs[p] = list(self.subcontexts[p].keys())
            for sub in self.subcontexts[p].values():
                bs.update(**{k: v for k, v in sub.all_bindings.items() if k != p})
        return bs

    @property
    def all_bindings(self):
        return {**{k: [v] for k, v in self.bindings.items()}, **self._all_bindings()}

    def messages(self, schema=None, **kwargs):
        if self.parent:
            yield from self.parent.messages(schema, **kwargs)

        yield from filter(
            lambda m: (not schema or m.schema == schema)
            and all(check(m[k], kwargs[k]) for k in kwargs),
            self._messages.values(),
        )

    def _all_messages(self, schema=None, **kwargs):
        yield from filter(
            lambda m: (not schema or m.schema == schema)
            and all(check(m[k], kwargs[k]) for k in kwargs),
            self._messages.values(),
        )
        for p in self.subcontexts:
            for sub in self.subcontexts[p].values():
                yield from sub._all_messages(schema, **kwargs)

    def all_messages(self, schema=None, **kwargs):
        if self.parent:
            yield from self.parent.messages(schema, **kwargs)
            yield from self._all_messages(schema, **kwargs)
        else:
            yield from self._all_messages(schema, **kwargs)

    def find(self, schema):
        m = self._messages.get(schema)
        if m:
            return m
        else:
            for p in self.subcontexts:
                for sub in self.subcontexts[p].values():
                    m = sub.find(schema)
                    if m:
                        return m

    def __repr__(self):
        return f"Context(bindings={self.bindings},messages={[m for m in self.messages()]},subcontexts={self.subcontexts})"

    def instance(self, schema):
        payload = {}
        for k in schema.parameters:
            payload[k] = self.bindings[k]
        return Message(schema, payload)

    def __getitem__(self, key):
        return self.subcontexts[key]

    def __setitem__(self, key, value):
        self.subcontexts[key] = value
        return value

    def __contains__(self, key):
        return key in self.subcontexts

    def keys(self):
        return self.subcontexts.keys()

    def flatten_subs(self):
        for p in self.subcontexts:
            for v in self.subcontexts[p]:
                yield self.subcontexts[p][v]

    def flatten(self):
        yield self
        yield from self.flatten_subs()


class Store:
    def __init__(self, systems):
        """
        Construct a store, with separate contexts for each of the system IDs in `systems`.
        """
        # message indexes
        # recursive (key -> value -> context -> subkey -> value -> subcontext...)
        self.contexts = {k: Context() for k in systems}

    def messages(self, *args, **kwargs):
        for c in self.contexts.values():
            yield from c.all_messages(*args, **kwargs)

    def matching_contexts(self, message):
        """Find contexts that either have the same bindings, or don't have the parameter"""

        context = self.context(message)

        if len(context.subcontexts):
            return [
                c
                for c in context.flatten()
                if all(
                    c.bindings.get(p) == message[p] or p not in c.bindings
                    for p in message.payload
                )
            ]
        else:
            return [context]

    def check_integrity(self, message, context=None):
        """
        Make sure payload can be received.

        Each message in context should have the same keys.
        Returns true if the parameters are consistent with all messages in the matching context.
        """
        context = context or self.context(message)
        result = all(
            message.payload[p] == context.bindings[p]
            for p in message.payload
            if p in context.bindings
        )
        return result

    def check_outs(self, schema, context):
        """
        Make sure none of the outs have been previous bound to a different value.
        Only use this check if the message is being sent.
        Assumes message is not a duplicate.
        """
        # context may be parent, if there are no matches; possibly even the root
        return not any(p in context.bindings for p in schema.outs)

    def check_nils(self, schema, context):
        """
        Make sure none of the nils are bound.
        Only use this check if the message is being sent.
        """
        # context may be parent, if there are no matches; possibly even the root
        return not any(p in context.bindings for p in schema.nils)

    def check_dependencies(self, message, context):
        """
        Make sure that all 'in' parameters are bound and matched by some message in the history
        """
        for p in message.schema.ins:
            # bindings that only match on a subset of keys are ok
            # bindings with any contradictory keys are not; should be handled by integrity though
            # this logic is not quite correct, and is inefficient - TODO
            c = context
            while c:
                if message.payload[p] in c.all_bindings.get(p, []):
                    return True
                else:
                    c = c.parent
            print(f"message: {message}, ins: {message.schema.ins}")
            print(f"context: {context}")
            logger.info(f"{p} is not found in {context.all_bindings}")
            exit(1)
            return False
        return True

    def check_emissions(self, messages, use_context=None):
        # message assumed not to be duplicate; otherwise recheck unnecessary
        parameters = {}
        for message in messages:
            context = use_context or self.context(message)
            if not self.check_outs(message.schema, context):
                logger.info(
                    f"Failed {message.schema.name} out check: {message.payload}"
                )
                return False

            if not self.check_nils(message.schema, context):
                logger.info(
                    f"Failed {message.schema.name} nil check: {message.payload}; context: {context}"
                )
                return False

            if not self.check_integrity(message, context):
                logger.info(
                    f"({message.schema.sender.name}) Integrity violation: {message} not consistent with context {context}"
                )
                return False

            if not self.check_dependencies(message, context):
                logger.info(f"Failed dependency check for {message}")
                return False

            if message.schema.disabled_by(parameters.get(message.key, set())):
                logger.info(
                    f"Message {message} disabled by other emissions: {messages}"
                )
                return False

            if parameters.get(message.system, {}).get(message.key):
                parameters[message.system][message.key].update(
                    message.schema.ins.union(message.schema.outs)
                )
            else:
                if message.system not in parameters:
                    parameters[message.system] = {}
                parameters[message.system][message.key] = message.schema.ins.union(
                    message.schema.outs
                )

        return True

    def add(self, *messages):
        """
        Add a message instance to the store.
        """

        # log under the correct context
        for m in messages:
            context = self.context(m)
            context.add(m)

    def context(self, message, schema=None):
        """Find or create a context for message"""
        parent = None
        context = self.contexts[message.system]
        if not schema:
            schema = message.schema
        for k in schema.keys:
            v = message.payload.get(k)
            if k in context:
                if v is not None and v in context[k]:
                    new_context = context[k][v]
                else:
                    new_context = context[k][v] = Context(parent=parent)
            else:
                context[k] = {}
                context[k][v] = new_context = Context(parent=parent)
            context = new_context
            parent = context

        return context

    def is_duplicate(self, message):
        """
        Return true if payload has already been stored.
        """
        context = self.context(message)
        match = context._messages.get(message.schema)
        if match and match == message:
            return True
        elif match:
            raise Exception(
                "Message found with matching key {} but different parameters: {}, {}".format(
                    message.key, message, match
                )
            )
        else:
            return False

    def fill(self, message):
        context = self.context(message)
        bindings = context.bindings

        for p in message.schema.parameters:
            v = bindings.get(p)
            if v:
                message.payload[p] = v
            else:
                raise Exception(
                    f"Cannot complete message {message} with context {context}"
                )
        return message
