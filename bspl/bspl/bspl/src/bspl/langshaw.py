#!/usr/bin/env python3

from itertools import chain, product
from functools import reduce, partial
from .protocol import Protocol, Role, Parameter, Message
import re
from pathlib import Path
from .parsers.langshaw import load


def apply(a, f):
    return f(a)


def get_clause(spec, kind):
    for c in spec:
        if kind in c:
            return c[kind]
    return []


def delegates(parameter, schema=None):
    """Returns the name of the parameter being delegated by the argument
    e.g. delegates("item@S") == "item"
    """
    if schema:
        return [p for p in schema if delegates(p[0]) == parameter]
    m = re.match(r"(.*)@.*", parameter)
    if m:
        return m.groups()[0]


def delegations(schema, role=None):
    """
    Returns a list of delegations in the schema
    If a role is provided, return only delegations to other roles
    """
    if role:
        return [p for p in schema if delegates(p[0]) and not delegates_to(p[0]) == role]
    else:
        return [p for p in schema if delegates(p[0])]


def delegates_to(parameter):
    """Returns the role being delegated to by the argument
    e.g. delegates("item@S") == "S"
    """
    m = re.match(r".*@(.*)", parameter)
    if m:
        return m.groups()[0]


def some(f, name):
    def wrap(v):
        # only call f on v if v is not None
        if v != None:
            result = f(v)
            # if not result:
            #     print(f"{name} dropped {v}")
            return result

    return wrap


def getp(name, schema):
    "find parameter in schema by name"
    return next((p for p in schema if p[0] == name), None)


def handle_delegation(protocol, role):
    """
    p = nil => p@other != nil
    p@other = in => p = in
    p@other = out => role can delegate p and p != out or in
    p@other = nil => p != nil
    """

    def inner(s):
        for p in s:
            if p[1] == "nil" and not delegates(p[0]):
                if not any(
                    delegates(d[0]) == p[0] and d[1] == "out"
                    for d in delegations(s, role)
                ):
                    return  # p is nil, but not delegated to other role

        for d in delegations(s):
            if delegates_to(d[0]) != role:
                # not a delegation to this role
                p = delegates(d[0])  # parameter being delegated
                ad = getp(p, s)[1]  # delegated parameter's adornment
                if d[1] == "in" and ad != "in":
                    # already delegated to other role, must already be bound
                    return
                elif d[1] == "out" and ad != "nil":
                    # if delegation is out, parameter must be nil
                    return
                elif d[1] == "nil" and ad == "nil":
                    # if delegation is nil, parameter not must be nil
                    pass  # return
            else:
                # delegation to self
                if d[1] == "out":
                    return  # can't delegate to self
        return s

    return some(inner, "handle_delegation")


def ensure_priority(protocol, role):
    """
    Ensure that schemas reflect the priority of the actor.
    If the actor is not first, it may only bind or delegate if it has been delegated to.
    """

    def inner(s):
        for p in s:
            if protocol.can_be_delegated(role, p[0]):
                # not the first priority
                d_in = f"{p[0]}@{role}"
                if getp(d_in, s) and getp(d_in, s)[1] != "in":
                    # didn't receive delegation
                    to = protocol.delegates_to(role, p[0])
                    d_out = f"{p[0]}@{to}"
                    if (to and getp(d_out, s)[1] == "out") or getp(p[0], s)[1] == "out":
                        # can't delegate or bind
                        return
        return s

    return some(inner, "ensure_priority")


def handle_exclusivity(protocol, role):
    "If a role has exclusive sayso for a parameter, and it only appears in one message, it must be out"

    def inner(s):
        for p in s:
            ps = protocol.priorities(p[0])
            if role in ps and len(ps) == 1:
                # has exclusive sayso for p
                actions = [
                    a
                    for a in protocol.actions
                    if any(ap == p[0] and a.actor == role for ap in a.parameters)
                ]
                if len(actions) == 1:
                    if getp(p[0], s)[1] != "out":
                        return
        return s

    return some(inner, "handle_exclusivity")


def out_keys(keys):
    "Some key must be in if any parameter is in"

    def inner(s):
        if not any(p[1] == "in" for p in s if p[0] not in keys):
            return s
        if any(p[1] == "in" for p in s if p[0] in keys):
            return s

    return some(inner, "out_keys")


class Action:
    def __init__(self, spec, parent):
        self.spec = spec
        self.parent = parent

        self.actor = spec["actor"]
        self.name = spec["name"]
        self.parameters = spec["parameters"]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @property
    def keys(self):
        return [p for p in self.parameters if p in self.parent.keys]

    @property
    def non_keys(self):
        return [p for p in self.parameters if p not in self.parent.keys]

    @property
    def delegations(self):
        """Returns a sequence of delegations for this action, where a
        delegation is a name of the form 'parameter@role'
        """
        for p in self.non_keys:
            if self.parent.can_be_delegated(self.actor, p):
                yield f"{p}@{self.actor}"
            to = self.parent.delegates_to(self.actor, p)
            if to:
                yield f"{p}@{to}"

    @property
    def autonomy_parameter(self):
        return self.name

    @property
    def explicit_dependencies(self):
        """Return the actions that this action explicitly depends on (by referencing its name)"""
        deps = []
        for p in self.parameters:
            a = self.parent.action(p)
            if a and a != self:
                deps.append(a)
        return deps

    @property
    def expanded_parameters(self):
        yield from self.keys
        for p in self.non_keys:
            if "out" in self.possibilities(p):
                yield from self.parent.delegations(self.actor, p)
            yield p
        yield self.autonomy_parameter

    def possibilities(self, parameter):
        if parameter in self.keys:
            # keys can't be nil
            return ["in", "out"]
        elif parameter == self.autonomy_parameter:
            # autonomy parameter for this action is always out
            return ["out"]
        elif self.parent.action(parameter):
            # autonomy parameters for other actions are always in
            return ["in"]
        elif delegates(parameter) and delegates_to(parameter) == self.actor:
            # incoming delegations may not be bound
            return ["in", "nil"]
        elif self.parent.can_bind(self.actor, parameter):
            # collect possibilities for parameter in explicit dependencies
            pss = []
            for p in self.parameters:
                a = self.parent.action(p)
                if a and a != self:
                    pss.append(a.possibilities(parameter))
            # if there are such possibilities, and role can't bind parameter
            if pss and [ps for ps in pss if ps]:
                if delegates(parameter):
                    # after first appearance of the delegation, always in/nil
                    return ["in", "nil"]
                pss = min(set(ps) for ps in pss if ps)
                if "nil" in pss:
                    # if actor can delegate the parameter, doesn't have to bind
                    if self.parent.delegates_to(self.actor, parameter):
                        return ["in", "out", "nil"]
                    # if this is the 'end of the line', have to receive or bind it
                    else:
                        return ["in", "out"]
                else:
                    # some dependency has in/out, so it must already be bound
                    return ["in"]
            # if the actor can bind the parameter, it can be anything
            return ["in", "out", "nil"]
        elif parameter in self.non_keys:
            return ["in"]
        elif parameter not in self.expanded_parameters:
            # not one of ours; no possibilities
            return []

    def columns(self):
        for p in self.expanded_parameters:
            yield product([p], self.possibilities(p))

    def all_schemas(self):
        return product(*self.columns())

    def schemas(self):
        return filter(
            lambda s: s,
            map(
                # call each filter function on s
                # each function passes it on if it succeeds the test
                # but short-circuits if passed None
                lambda s: reduce(
                    apply,
                    [
                        out_keys(self.keys),
                        handle_delegation(self.parent, self.actor),
                        ensure_priority(self.parent, self.actor),
                        handle_exclusivity(self.parent, self.actor),
                    ],
                    s,
                ),
                self.all_schemas(),
            ),
        )


def parameters(spec):
    return [p["name"] for pc in get_clause(spec, "what") for p in pc]


def validate(spec):
    # ensure there aren't multiple sayso clauses involving the same parameters
    for p in parameters(spec):
        clauses = [s for s in get_clause(spec, "saysos") if p in s["parameters"]]
        if len(clauses) > 1:
            clauses = "\n  ".join(map(str, clauses))
            raise Exception(
                f"Parameter {p} should only appear in one sayso clause:\n  {clauses}"
            )
    return True


class Langshaw:
    def __init__(self, spec):
        self.source = spec
        if isinstance(spec, str):
            spec = load(spec)
        validate(spec)
        self.spec = spec
        self.actions = [Action(a, self) for a in self.get_clause("actions")]
        self.autonomy_parameters = set(a.autonomy_parameter for a in self.actions)

    @classmethod
    def load_file(cls, path):
        source = Path(path).read_text()
        inst = cls(source)
        return inst

    def get_clause(self, kind):
        return get_clause(self.spec, kind)

    def action(self, name):
        for a in self.actions:
            if a.name == name:
                return a

    @property
    def name(self):
        return self.get_clause("name")

    @property
    def roles(self):
        return self.get_clause("who")

    @property
    def parameters(self):
        return [p["name"] for pc in self.get_clause("what") for p in pc]

    @property
    def what(self):
        return self.get_clause("what")

    @property
    def private(self):
        return (
            set(a.name for a in self.actions)
            .union(p for a in self.actions for p in a.parameters)
            .difference(self.parameters)
            .union(a.autonomy_parameter for a in self.actions)
            .union(self.alt_parameters.values())
            .union(self.all_delegations)
            .union({c for a in self.actions for c in self.copies(a)})
            .union({"conflict" + str(i) for i in range(len(self.conflicts))})
        )

    @property
    def keys(self):
        for pc in self.get_clause("what"):
            for p in pc:
                if "key" in p and p["key"] != None:
                    yield p["name"]

    @property
    def conflicts(self):
        return self.get_clause("conflicts") or []

    @property
    def nogos(self):
        return self.get_clause("nogos") or []

    def conflicting(self, a, b):
        "Check if actions a and b are in mutual conflict (nono)"
        if a == b:
            return False
        for c in self.conflicts:
            if a.name in c and b.name in c:
                return True

    def prevents(self, a, b):
        "Check if action a prevents action b (nogo)"
        for c in self.nogos:
            # return true if a is before b in list c
            if a.name in c and b.name in c and c.index(a.name) < c.index(b.name):
                return True

    @property
    def saysos(self):
        return self.get_clause("saysos")

    def priorities(self, parameter):
        for c in self.saysos:
            if parameter in c["parameters"]:
                return c["roles"]
        return []

    def has_priority(self, a, b, p):
        "Return true if actor a has priority over b for parameter p"
        priority = self.priorities(p)
        if a in priority and b in priority:
            # Both are in the list, check which one comes first
            return priority.index(a) < priority.index(b)
        elif a in priority:
            # Only a is in the list; it has priority
            return True
        elif b in priority:
            # Only b is in the list
            return False
        else:
            # Neither is in the list
            return None

    def can_bind(self, role, parameter):
        """Check if role can bind parameter in some message (ignoring priority)"""

        if parameter in self.keys:
            return True

        for c in self.saysos:
            if role in c["roles"]:
                if parameter in c["parameters"]:
                    return True

        # only the actor can bind an action's autonomy parameters
        for a in self.actions:
            if parameter == a.autonomy_parameter and a.actor == role:
                return True
            elif parameter == a.autonomy_parameter and a.actor != role:
                return False

        # an actor can bind delegations to the next actor in the priority list
        p = delegates(parameter)
        if p and delegates_to(parameter) == self.delegates_to(role, p):
            return True

        # uncomment if anyone can bind parameters that aren't in a sayso clause
        # return not any(parameter in c["parameters"] for c in self.saysos)

    def can_be_delegated(self, role, parameter):
        """
        Returns true if role can be delegated parameter;
        In other words, if role is in the priority list for parameter but not first
        """
        roles = self.priorities(parameter)
        if roles:
            return role in roles and roles.index(role) > 0

    def delegates_to(self, role, parameter):
        "Returns the next role in the priority list for parameter after role, if any"
        roles = self.priorities(parameter)
        if roles and role in roles:
            pos = roles.index(role)
            if pos + 1 < len(roles):
                return roles[pos + 1]

    def delegations(self, role, parameter):
        if self.can_be_delegated(role, parameter):
            yield f"{parameter}@{role}"
        to = self.delegates_to(role, parameter)
        if to:
            yield f"{parameter}@{to}"

    @property
    def all_delegations(self):
        ds = set()
        for r in self.roles:
            for a in self.actions:
                for p in a.parameters:
                    for d in self.delegations(r, p):
                        ds.add(d)
        return ds

    def can_see(self, role, action):
        """
        Return true if role can see action:
          1. role can perform the action
          2. one of the role's actions references it by name
          3. (a) one of the role's actions (a) references an attribute p in the action
             (b) the performer of action (role r1) has sayso on p but r1's sayso on attribute p1 is not dominated by role
          4. it completes the protocol
        """
        # 1. role can perform the action
        if action.actor == role:
            return True

        # 2. one of the role's actions references it by name
        for a in self.actions:
            if a.actor == role and action.name in a.parameters:
                return True

        # 3. (a) one of the role's actions references an attribute p in some action a
        for a in self.actions:
            if a.actor == role:
                for p in a.parameters:
                    if p in action.parameters:
                        # (b) the performer of action (role r1) has sayso on p but r1's sayso on attribute p1 is not dominated by role
                        if not self.has_priority(action.actor, role, p):
                            return True

        # 4. it completes the protocol
        # include actions mentioned in the 'what' clauses
        for c in self.get_clause("what"):
            # there are multiple parameters in each clause
            for p in c:
                # if the names match, the action is in the what line, and should be visible
                if action.name == p["name"]:
                    return True

    def observes(self, role, parameter):
        """
        Check if a role can observe a parameter or not.
        Roles should be able to observe all parameters from actions they can see."""
        for a in self.actions:
            if parameter == a.name and self.can_see(role, a):
                # it's an action name, and the role can see the action
                return True
            if self.can_see(role, a) and parameter in a.parameters:
                print(f"{role} observes {parameter}")
                return True

    def observers(self, parameter):
        "A sequence of roles that can observe parameter"
        for r in self.roles:
            if self.observes(r, parameter):
                yield r

    def extend_schemas(self, action):
        # add nil parameters for conflicts
        conflicts = []
        for i, c in enumerate(self.conflicts):
            if action.name in c:
                conflicts.append("conflict" + str(i))

        # if action is second in a nogo, add nil for the other message
        nogos = []
        for c in self.nogos:
            if action.name in c and c.index(action.name) == 1:
                preventer = c[
                    0
                ]  # the first message in a nogo clause prevents the second
                nogos.append(preventer)

        for s in action.schemas():
            extended = s
            # add conflicts using 'out' parameters on each conflicting message
            extended = reduce(lambda s, c: s + ((c, "out"),), conflicts, extended)
            # add nogos using a nil parameter, which asymmetrically prevents the second message
            extended = reduce(
                lambda s, preventer: s + ((preventer, "nil"),), nogos, extended
            )
            yield extended

    @property
    def alt_parameters(self):
        alts = {}
        i = 0
        for c in self.get_clause("what"):
            if len(c) > 1:
                for p in c:
                    alts[p["name"]] = f"done{i}"
                i += 1
        return alts

    def recipients(self, action):
        """
        The set of roles that can receive action
        Recipients are roles that can see the action, except the actor
        """
        recipients = set()
        for r in self.roles:
            if r != action.actor and self.can_see(r, action):
                # if the role can see the action, it can receive the message
                recipients.add(r)
        return recipients

    def copies(self, action):
        """
        The copies of an action that must be sent to other roles
        """
        return [
            action.autonomy_parameter + str(i + 1)
            for i in range(len(self.recipients(action)))
            if i != 0
        ]

    def messages(self, action, protocol=None):
        for s in self.extend_schemas(action):
            n = 0
            for r in self.recipients(action):
                parameters = []
                for p in s:
                    if p[0] == action.autonomy_parameter:
                        aps = []
                        if n == 0:
                            aps.append(Parameter(p[0], "out"))
                        else:
                            # increment index for copies to subsequent recipients
                            aps.append(Parameter(p[0], "in"))
                            aps.append(Parameter(p[0] + str(n + 1), "out"))
                        parameters.extend(aps)
                    elif n == 0 or p[1] != "nil":
                        # don't include nil parameters in copies
                        parameters.append(
                            Parameter(p[0], p[1] if n == 0 or p[1] != "out" else "in")
                        )

                yield Message(
                    parent=protocol,
                    name=action.name,
                    sender=action.actor,
                    recipients=[Role(r)],
                    parameters=parameters,
                    validate=False,
                )
                n += 1

    def completion_messages(self, protocol=None):
        for p in self.alt_parameters:
            keys = set()
            for a in self.actions:
                if p in a.expanded_parameters:
                    for k in a.keys:
                        keys.add(k)
            for s in self.roles:
                if self.can_bind(s, p):
                    alt = self.alt_parameters[p]
                    r = next(o for o in self.observers(p) if o != s)
                    yield Message(
                        name=f"{p}-{alt}",
                        parent=protocol,
                        sender=s,
                        recipients=[r],
                        parameters=[Parameter(k, "in", "key") for k in keys]
                        + [Parameter(p, "in"), Parameter(alt, "out")],
                        validate=False,
                    )

    def to_bspl(self, name):
        p = Protocol(
            name,
            roles=self.roles,
            public_parameters=[
                Parameter(p, "out", key=p in self.keys)
                for p in self.parameters
                if p not in self.alt_parameters
            ]
            + [Parameter(p, "out") for p in set(self.alt_parameters.values())],
            private_parameters=[Parameter(p, None) for p in self.private],
        )
        for r in chain(
            (m for a in self.actions for m in self.messages(a, p)),
            self.completion_messages(p),
        ):
            p.add_reference(r)
        return p
