from .utils import merge, upcamel
import inspect
import sys
import re
import copy
from types import ModuleType


class ProtoMod(ModuleType):
    def __setitem__(self, name, value):
        return self.__setattr__(name, value)

    def __getitem__(self, name):
        return self.__getattribute__(name)


class Specification:
    def __init__(self, protocols=None):
        self.protocols = {}  # name : protocol
        self.type = "specification"
        if protocols:
            self.add_protocols(protocols)

    def add_protocols(self, protocols=list()):
        # store protocol by name
        for p in protocols:
            self.protocols[p.name] = p

        for p in self.protocols.values():
            p.resolve_references(self)

        # Validate parameter consistency after references are resolved
        from .validation import validate_protocol_parameters

        for p in self.protocols.values():
            validate_protocol_parameters(p)

    def export(self, protocol):
        p = self.protocols[protocol]
        frm = inspect.stack()[1]
        module = ProtoMod(p.name)

        for name, message in p.messages.items():
            module[name] = message

        for name, role in p.roles.items():
            module[name] = role

        # Export sub-protocols for unqualified message access
        for ref in p.references.values():
            if hasattr(ref, "type") and ref.type == "protocol":
                # Create a safe module name (replace spaces with underscores)
                safe_name = ref.name.replace(" ", "_").replace("-", "_")
                module[safe_name] = ref

        module.protocol = p
        sys.modules[p.name] = module
        p.module = module
        return p

    # @classmethod
    # def from_json(cls, protocols):
    #     return cls([Protocol.from_dict(p, self) for p in protocols])

    @property
    def messages(self):
        return set(m for p in self.protocols.values() for m in p.messages.values())


class Base:
    """Class containing elements common to protocols, messages, etc."""

    def __init__(self, name, parent, kind):
        self.raw_name = name.strip()
        self.parent = parent
        self.type = kind
        if type(parent) is Specification:
            self.spec = parent
            self.parent_protocol = None
        elif type(parent) is Protocol:
            self.spec = getattr(parent, "spec", None)
            self.parent_protocol = parent
        elif parent:
            self.spec = getattr(parent, "spec", None)
            self.parent_protocol = parent.parent_protocol
        else:
            self.spec = None
            self.parent_protocol = None

    @property
    def name(self):
        return self.raw_name

    # @classmethod
    # def from_dict(cls, data, parent=None):
    #     return cls(data["name"].strip(), parent, schema["type"])


class Role(Base):
    def __init__(self, name, parent=None):
        super().__init__(name, parent, "role")

    def messages(self, protocol=None):
        protocol = protocol or self.parent
        return {
            m.name: m
            for m in protocol.messages.values()
            if m.sender == self or self in m.recipients
        }

    def emissions(self, protocol):
        return [m for m in protocol.messages.values() if m.sender == self]

    def receptions(self, protocol):
        return [m for m in protocol.messages.values() if self in m.recipients]

    def observations(self, protocol):
        return self.emissions(protocol) + self.receptions(protocol)

    def dependencies(self, em):
        """Return a list of messages that are necessary for"""


class Reference(Base):
    def __init__(self, name, parameters=None, parent=None):
        self.parameters = parameters  # list(Parameter)
        super().__init__(name, parent, "reference")

    @property
    def name(self):
        return self.raw_name + (str(self.idx) if getattr(self, "idx", 1) > 1 else "")

    def format(self, ref=True):
        return "{}({}, {})".format(
            self.name,
            ", ".join([r.name for r in self.roles]),
            ", ".join([p.format() for p in self.parameters]),
        )


class Protocol(Base):
    def __init__(
        self,
        name,
        roles=None,
        public_parameters=None,
        references=None,
        parent=None,
        private_parameters=None,
        type="protocol",
        autoregister_privates=False,
    ):
        super().__init__(name, parent, type)
        self.public_parameters = {}
        self.private_parameters = {}
        self.roles = {}
        self.references = {}
        self.autoregister_privates = autoregister_privates
        Protocol.configure(
            self, roles, public_parameters, private_parameters, references
        )

    def configure(
        self,
        roles=None,
        public_parameters=None,
        private_parameters=None,
        references=None,
        parent=None,
    ):
        parent = self.parent = getattr(self, "parent", parent)
        if roles:
            for r in roles or []:
                if type(r) is Role:
                    self.roles[r.name] = r
                elif type(r) is str:
                    self.roles[r] = Role(r, self)
                else:
                    raise ("{} is unexpected type: {}".format(r, type(r)))
        if public_parameters:
            self.set_parameters(public_parameters)
        if private_parameters:
            self.private_parameters = {p.name: p for p in private_parameters}
        if references:
            self.references = {}
            for r in references:
                self.add_reference(r)

    def add_reference(self, reference):
        duplicates = 1
        for r in self.references.values():
            if r.raw_name == reference.raw_name:
                duplicates += 1
        reference.idx = duplicates
        self.references[reference.name] = reference

    def set_parameters(self, parameters):
        self.public_parameters = {p.name: p for p in parameters}

    @property
    def parameters(self):
        return {**self.public_parameters, **self.private_parameters}

    @property
    def ins(self):
        return self.adorned("in")

    @property
    def outs(self):
        return self.adorned("out")

    @property
    def nils(self):
        return self.adorned("nil")

    @property
    def keys(self):
        return self.get_keys()

    def add_private(self, parameter):
        self.private_parameters[parameter.name] = parameter

    @property
    def all_parameters(self):
        return {p for m in self.messages.values() for p in m.parameters}

    def get_keys(self):
        return {
            p.name: p
            for p in self.parameters.values()
            if p.key
            or self.parent
            and self.parent.type == "protocol"
            and p.name in self.parent.parameters
            and self.parent.parameters[p.name].key
        }

    def adorned(self, adornment):
        "helper method for selecting parameters with a particular adornment"
        return {
            p.name for p in self.public_parameters.values() if p.adornment == adornment
        }

    @property
    def messages(self):
        result = {}
        for r in self.references.values():
            if hasattr(r, "type") and r.type == "message":
                # Direct messages: use unqualified names
                for v in r.messages.values():
                    result[v.name] = v
            else:
                # Protocol references: use qualified names
                for v in r.messages.values():
                    result[v.qualified_name] = v
        return result

    @property
    def is_entrypoint(self):
        "A protocol is an entry point if it does not have any \
        dependencies on sibling protocols"
        return not self.ins - self.parent.ins

    @property
    def entrypoints(self):
        return [m for m in self.messages.values() if m.is_entrypoint]

    def format(self, ref=False):
        if ref:
            return "{}({}, {})".format(
                self.name,
                ", ".join(self.roles),
                ", ".join([p.format() for p in self.public_parameters.values()]),
            )
        else:
            return """{} {{
  roles {}
  parameters {}
{}
  {}
}}""".format(
                self.name,
                ", ".join(self.roles.keys()),
                ", ".join([p.format() for p in self.public_parameters.values()]),
                (
                    "  private "
                    + ", ".join([p for p in self.private_parameters])
                    + "\n"
                    if self.private_parameters
                    else ""
                ),
                "\n  ".join([r.format(ref=True) for r in self.references.values()]),
            )

    def to_dict(self):
        data = {
            "name": self.name,
            "type": self.type,
            "parameters": [p for p in self.public_parameters.keys()],
            "keys": [k for k in self.keys],
            "ins": [i for i in self.ins],
            "outs": [i for i in self.outs],
            "nils": [i for i in self.nils],
        }
        if self.roles:
            data["roles"] = [r for r in self.roles.keys()]
        # should we output references, or just flatten to messages?
        if self.references:
            data["messages"] = {r.name: r.to_dict() for r in self.messages.values()}
        return data

    def projection(protocol, role):
        references = [
            r
            for r in protocol.references.values()
            if role in r.roles.values()
            or r.type == "message"
            and (role == r.sender or role == r.recipient)
        ]

        messages = [m for m in references if m.type == "message"]

        if len(messages) > 0:
            return Protocol(
                protocol.name,
                public_parameters=[
                    p
                    for p in protocol.public_parameters.values()
                    if any(p.name in m.parameters for m in messages)
                ],
                private_parameters=[
                    p
                    for p in protocol.private_parameters.values()
                    if any(p.name in m.parameters for m in messages)
                ],
                roles=[
                    r
                    for r in protocol.roles.values()
                    if any(
                        m.sender.name == r.name or m.recipient.name == r.name
                        for m in messages
                    )
                ],
                references=[r for r in references],
                parent=protocol.parent,
            )

    def resolve_references(self, spec):
        refs = {}
        for r in self.references.values():
            if r.type == "protocol" or r.type == "reference":
                protocol = spec.protocols.get(r.raw_name)
                if not protocol:
                    raise LookupError(f"Undefined protocol {r.name}")
                refs[r.name] = protocol.instance(spec, self, r)
            elif r.type == "message":
                refs[r.name] = r.instance(self)
            else:
                print(f"Unexpected reference type: {r.type}")
        self.references = refs

    def instance(self, spec, parent, reference):
        p = Protocol(
            reference.name,
            self.roles.values(),
            public_parameters=self.public_parameters.values(),
            private_parameters=self.private_parameters.values(),
            references=[copy.deepcopy(r) for r in self.references.values()],
            parent=parent,
        )
        for i, r in enumerate(self.roles.values()):
            # print(f"{reference}[{i}]: {r}")
            p.roles[r.name] = parent.roles.get(reference.parameters[i].name)
        for i, par in enumerate(self.public_parameters.values()):
            ref_name = reference.parameters[i + len(p.roles)].name
            if ref_name not in parent.parameters:
                if parent.autoregister_privates:
                    self.add_private()

                raise LookupError(
                    f"Parameter {ref_name} from reference {reference.name} not declared in parent {parent.name}"
                )
            p.public_parameters[par.name] = parent.parameters[ref_name]
        p.resolve_references(spec)
        return p

    def find_schema(self, payload=None, name=None, to=None):
        if name:
            return self.messages[name]

        for schema in self.messages.values():
            if to and schema.recipient is not to:
                continue
            # find schema with exactly the same parameters (except nils, which should not be bound)
            if (
                not set(schema.ins)
                .union(schema.outs)
                .symmetric_difference(payload.keys())
            ):
                return schema

    def determines(self, a, b):
        """
        a determines b if a is 'in' in all messages b is 'out'
        Expects a and b as str names
        """
        sources = {m for m in self.messages.values() if b in m.outs}
        for m in sources:
            if a not in m.ins:
                return False
        return True

    def ordered_params(self):
        return sorted(self.parameters.values())

    def initiators(self):
        return {m for m in self.messages.values() if len(m.ins) == 0}

    def __repr__(self):
        return self.name


class Message(Protocol):
    def __init__(
        self,
        name,
        sender=None,
        recipients=None,
        parameters=None,
        parent=None,
        idx=1,
        validate=True,
    ):
        self.idx = idx
        self.validate = validate
        self.msg = self

        if sender and recipients:
            # Handle both single recipient (backwards compatibility) and multiple recipients
            if isinstance(recipients, str):
                recipients = [recipients]
            all_roles = [sender] + recipients
            super().__init__(
                name, roles=all_roles, parent=parent, type="message"
            )
            self.configure(sender, recipients, parameters, parent)
        else:
            super().__init__(name, parent=parent, type="message")

    def configure(self, sender=None, recipients=None, parameters=None, parent=None):
        parent = parent or getattr(self, "parent", None)
        
        # Handle backwards compatibility: single recipient as string
        if isinstance(recipients, str):
            recipients = [recipients]
        elif recipients is None:
            recipients = []
            
        if parent:
            self.sender = parent.roles.get(sender) or parent.roles.get(
                getattr(sender, "name", None)
            )
            self.recipients = []
            for recipient in recipients:
                resolved_recipient = parent.roles.get(recipient) or parent.roles.get(
                    getattr(recipient, "name", None)
                )
                if resolved_recipient:
                    self.recipients.append(resolved_recipient)
            for p in parameters or []:
                if self.validate and p.name not in parent.parameters:
                    raise LookupError(
                        f"Undeclared parameter '{p.name}' in {self.type} '{self.name}'"
                    )
                elif p.name in parent.parameters and parent.parameters[p.name].key:
                    p.key = True
        else:
            self.sender = sender if isinstance(sender, Role) else Role(sender, self)
            self.recipients = []
            for recipient in recipients:
                if isinstance(recipient, Role):
                    self.recipients.append(recipient)
                else:
                    self.recipients.append(Role(recipient, self))

        if self.validate:
            if not self.sender:
                available_roles = list(parent.roles.keys()) if parent and hasattr(parent, 'roles') else []
                error_msg = ""
                if parent:
                    error_msg += f"In protocol '{parent.name}':\n"
                error_msg += f"Message '{self.name}' references unknown sender '{sender}'"
                if available_roles:
                    error_msg += f"\nAvailable roles: {', '.join(available_roles)}"
                    # Fuzzy matching using difflib
                    import difflib
                    similar = difflib.get_close_matches(str(sender), available_roles, n=3, cutoff=0.6)
                    if similar:
                        if len(similar) == 1:
                            error_msg += f"\nDid you mean '{similar[0]}' instead of '{sender}'?"
                        else:
                            error_msg += f"\nDid you mean one of: {', '.join(similar)}?"
                    else:
                        error_msg += f"\nIf '{sender}' is a new role, add it to the roles declaration."
                raise LookupError(error_msg)
            
            if not self.recipients:
                available_roles = list(parent.roles.keys()) if parent and hasattr(parent, 'roles') else []
                error_msg = ""
                if parent:
                    error_msg += f"In protocol '{parent.name}':\n"
                error_msg += f"Message '{self.name}' references unknown recipient(s): {recipients}"
                if available_roles:
                    error_msg += f"\nAvailable roles: {', '.join(available_roles)}"
                    # Fuzzy matching for each recipient
                    import difflib
                    suggestions_found = False
                    for recipient in recipients:
                        similar = difflib.get_close_matches(str(recipient), available_roles, n=3, cutoff=0.6)
                        if similar:
                            if len(similar) == 1:
                                error_msg += f"\nDid you mean '{similar[0]}' instead of '{recipient}'?"
                            else:
                                error_msg += f"\nFor '{recipient}', did you mean one of: {', '.join(similar)}?"
                            suggestions_found = True
                    if not suggestions_found:
                        unknown_recipients = [str(r) for r in recipients]
                        if len(unknown_recipients) == 1:
                            error_msg += f"\nIf '{unknown_recipients[0]}' is a new role, add it to the roles declaration."
                        else:
                            error_msg += f"\nIf {', '.join(unknown_recipients)} are new roles, add them to the roles declaration."
                raise LookupError(error_msg)

        super().configure(
            roles=[self.sender] + self.recipients,
            public_parameters=parameters,
            parent=parent,
        )

    @property
    def qualified_name(self):
        return self.parent.name + "/" + self.name
    
    @property 
    def recipient(self):
        """Backwards compatibility property - returns first recipient"""
        return self.recipients[0] if self.recipients else None

    @property
    def name(self):
        return self.raw_name + (str(self.idx) if self.idx > 1 else "")

    def __repr__(self):
        return self.name
        return "Message('{}', {}, {}, {})".format(
            self.name,
            self.sender.name,
            self.recipient.name,
            [p.format() for p in self.parameters.values()],
        )

    def instance(self, parent):
        msg = Message(
            self.raw_name,
            self.sender,
            self.recipients,
            self.parameters.values(),
            idx=self.idx,
            parent=parent,
        )

        # propagate parameters from parent protocol
        for i, par in enumerate(self.public_parameters.values()):
            # Make a new parameter, to preserve message adornments
            parent_parameter = parent.parameters[par.name]
            msg.public_parameters[par.name] = Parameter(
                parent_parameter.raw_name, par.adornment, par.key, parent=self
            )

        return msg

    @property
    def messages(self):
        return {self.name: self}

    def format(self, ref=False):
        recipients_str = ",".join([r.name for r in self.recipients])
        return "{} -> {}: {}[{}]".format(
            self.sender.name,
            recipients_str,
            self.raw_name,
            ", ".join([p.format() for p in self.parameters.values()]),
        )

    def to_dict(self):
        data = super(Message, self).to_dict()
        data["to"] = [r.name for r in self.recipients]
        data["from"] = self.sender.name
        return data

    @property
    def contents(self):
        return [
            p for p in self.parameters.values() if p.adornment in ["out", "any", "in"]
        ]

    def acknowledgment(self):
        name = "@" + self.raw_name
        try:
            return self.parent.messages[name]
        except KeyError:
            # For multiple recipients, create separate acknowledgment messages from each recipient to sender
            if len(self.recipients) == 1:
                # Single recipient - use original behavior
                m = Message(
                    "@" + self.raw_name, 
                    sender=self.recipients[0], 
                    recipients=[self.sender], 
                    parent=self.parent
                )
                m.set_parameters(
                    [Parameter(k, "in", key=True, parent=m) for k in self.keys]
                    + [Parameter("$ack", "out", key=True, parent=m)]
                )
                return m
            else:
                # Multiple recipients - create separate ack messages with unique parameters
                # Return the first one for backward compatibility, but all should be generated
                ack_messages = []
                for i, recipient in enumerate(self.recipients):
                    ack_name = f"@{self.raw_name}_{recipient.name}"
                    m = Message(
                        ack_name,
                        sender=recipient,
                        recipients=[self.sender],
                        parent=self.parent
                    )
                    # Each ack gets unique out parameter to avoid conflicts
                    ack_param_name = f"$ack_{recipient.name}"
                    m.set_parameters(
                        [Parameter(k, "in", key=True, parent=m) for k in self.keys]
                        + [Parameter(ack_param_name, "out", key=True, parent=m)]
                    )
                    ack_messages.append(m)
                
                # For backward compatibility, return first message
                # TODO: Consider changing return type to list in future
                return ack_messages[0]

    def validate(self, payload):
        return set(payload) == set(self.parameters.keys())

    def disabled_by(self, parameters):
        """
        Return true if parameters do not interfere with outs or nils

        parameters: set of parameter names
        """
        return self.outs.union(self.nils).intersection(parameters)

    def zip_params(self, *params):
        """Construct a payload from a list of parameter values"""
        return dict(
            zip(
                [
                    p
                    for p in self.public_parameters.keys()
                    if self.public_parameters[p].adornment in ("in", "out")
                ],
                params,
            )
        )

    def construct(self, *args, **kwargs):
        """Construct a (partial) payload from a positional and keyword values"""
        payload = {}
        # Ensure keys are declared
        for k in self.keys:
            payload[k] = None

        for i, p in enumerate(self.public_parameters):
            is_nil = self.parameters[p].adornment == "nil"
            if i < len(args):
                if args[i] and is_nil:
                    raise Exception(
                        f"Attempting to bind nil parameter: {p} = {args[i]}"
                    )
                elif not is_nil:
                    payload[p] = args[i]

        for k in kwargs:
            if k in self.parameters:
                payload[k] = kwargs[k]
            else:
                raise Exception(f"Parameter not in schema {self}: {k}")

        return payload

    def order_params(self, payload, default=None):
        """Yield each parameter from payload in the order the parameters appear
        in the message schema
        """
        for p in self.public_parameters.keys():
            if p in payload:
                yield payload[p]
            elif self.public_parameters[p].adornment != "nil":
                if not default:
                    yield None
                elif callable(default):
                    yield default()
                else:
                    yield default


class Parameter(Base):
    def __init__(self, name, adornment, key=False, parent=None):
        self.adornment = adornment
        self.key = key
        super().__init__(name, parent, "parameter")

    def format(self, adornment=True):
        if adornment:
            base = "{} {}".format(self.adornment, self.name)
        else:
            base = "{}".format(self.name)

        if self.key:
            return base + " key"
        else:
            return base

    def __lt__(self, other):
        return self.parent_protocol.determines(self.name, other.name)
