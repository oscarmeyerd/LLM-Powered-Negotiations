"""
Mambo - path queries for verifying arbitrary properties of information protocols
"""

from math import inf
from dataclasses import dataclass
from typing import Dict, Set, Tuple, Optional, Any, Callable
from .paths import (
    Emission,
    Reception,
    empty_path,
    possibilities,
    partition,
    UoD,
    max_paths,
)
from ..protocol import Protocol
from ..parsers.bspl import load_protocols
from ..parsers import precedence
from collections import defaultdict


def has_name_conflicts(spec, msg_name):
    """Check if a message name appears in multiple protocols within the spec."""
    count = 0
    for protocol in spec.protocols.values():
        if msg_name in [msg.name for msg in protocol.messages.values()]:
            count += 1
            if count > 1:
                return True
    return False


def get_smart_name(spec, msg):
    """Return qualified name if conflicts exist, otherwise return simple name."""
    if has_name_conflicts(spec, msg.name):
        return msg.qualified_name
    return msg.name


class Query:
    def __init__(self, *children):
        self.children = children
        if len(children) >= 1:
            self.a = children[0]
        if len(children) >= 2:
            self.b = children[1]

        self.conflicts = {}
        for c in children:
            if not isinstance(c, Query):
                continue
            for k, v in c.conflicts.items():
                if k in self.conflicts:
                    self.conflicts[k].update(v)
                else:
                    self.conflicts[k] = v

    @property
    def parameters(self):
        return set.union(*[c.parameters for c in self.children])

    def __call__(self, path: "Path", **kwargs):
        if kwargs.get("residuate", False):
            # Check if we have a memoized result
            if self in path.query_results:
                return path.query_results[self]

            value = self._call(path, **kwargs)
            if kwargs.get("verbose"):
                print(f"{self} = {value}")
            if isinstance(value, int):  # only save definite results (includes False)
                path.query_results[self] = value
            return value
        value = self._call(path, **kwargs)
        if kwargs.get("verbose"):
            print(f"{self} = {value}")
        return value

    def _call(self, path, **kwargs):
        raise NotImplementedError("Query subclasses must implement _call")

    def __repr__(self):
        return f"{type(self).__name__}({', '.join(str(c) for c in self.children)})"

    def __or__(self, other):
        return Or(self, other)

    def __and__(self, other):
        return And(self, other)

    def __invert__(self):
        return Not(self)

    def __neg__(self):
        return Not(self)

    def __lt__(self, other):
        return Before(self, other)


class Any(Query):
    """A query that always returns 0 (true at the beginning), regardless of the path"""

    def __str__(self):
        return "*"

    def _call(self, path, **kwargs):
        return 0


@dataclass
class Path:
    """A path that remembers query results"""

    events: Tuple[Any, ...]  # The actual path events
    query_results: Dict[Callable, Optional[int]]  # Memoized results for this path

    @classmethod
    def create_empty(cls) -> "Path":
        """Create an empty path with no events"""
        return Path(empty_path(), {})

    def extend(self, event) -> "Path":
        """Create a new path by adding an event"""
        new_events = self.events + (event,)
        return Path(new_events, self.query_results.copy())

    def __len__(self):
        return len(self.events)

    def __iter__(self):
        return iter(self.events)

    def __hash__(self):
        return hash(self.events)


def match_role(role, event):
    if not role:
        return True
    if isinstance(event, Emission):
        return role == event.sender or role == event.sender.name
    if isinstance(event, Reception):
        if hasattr(event, 'recipient') and event.recipient:
            return role == event.recipient or role == event.recipient.name
        else:
            # Fallback for backward compatibility
            return role in event.recipients or role in [r.name for r in event.recipients]
    return False


class Occurs(Query):
    _instances = {}

    # register unique instances of the same parameter
    def __new__(cls, key):
        if key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, p):
        super().__init__(p)
        self.p = p
        self.role = None
        self.protocol = None

        # Handle role:parameter format (existing functionality)
        if ":" in p:
            self.role, self.p = p.split(":")
        # Handle protocol/message format (new functionality)
        elif "/" in p:
            self.protocol, self.p = p.split("/", 1)

    @property
    def parameters(self):
        return {self.p}

    def __str__(self):
        if self.role:
            return f"{self.role}:{self.p}"
        elif self.protocol:
            return f"{self.protocol}/{self.p}"
        else:
            return self.p

    def _matches_event(self, e):
        """Check if this Occurs query matches the given event."""
        # Check if the event matches our message name
        name_matches = self.p == e.name
        param_matches = self.p in e.ins or self.p in e.outs

        if not (name_matches or param_matches):
            return False

        # If we have a protocol qualifier, only match if the event's message
        # has the same qualified name
        if self.protocol:
            return (
                hasattr(e, "msg")
                and hasattr(e.msg, "qualified_name")
                and e.msg.qualified_name == f"{self.protocol}/{self.p}"
            )

        # No protocol qualifier, match any message with this name/parameter
        return True

    def _call(self, path, **kwargs):
        # assume non-incremental by default to avoid surprises
        if kwargs.get("incremental", False) and kwargs.get("residuate", False):
            # only need to check the last event for new information
            if len(path.events) < 1:
                return
            e = path.events[-1]  # last
            if not match_role(self.role, e):
                return
            # match on name or ins/outs
            if self._matches_event(e):
                return len(path) - 1
        else:
            for i, e in enumerate(path):
                if not match_role(self.role, e):
                    continue
                if self._matches_event(e):
                    # nils don't count
                    return i


class Or(Query):
    def __str__(self):
        return f"({self.a} | {self.b})"

    def _call(self, path, **kwargs):
        val_a = self.a(path, **kwargs)
        val_b = self.b(path, **kwargs)
        types = [type(val_a), type(val_b)]
        if int in types:
            # int + int, inf, false, or none
            # even if the other resolves later, we know the minimum
            ints = [i for i in [val_a, val_b] if type(i) == int]
            return min(ints)
        if float in types:
            # inf + false or none
            return inf
        if type(None) in types:
            # none + false or none
            # indeterminate, could still become true
            return None
        # both are false; can't change
        return False


class And(Query):
    def __str__(self):
        return f"({self.a} & {self.b})"

    def _call(self, path, **kwargs):
        val_a = self.a(path, **kwargs)
        val_b = self.b(path, **kwargs)
        types = [type(val_a), type(val_b)]
        if bool in types:
            return False
        if type(None) in types:
            return None
        # assert type(val_a) == int and type(val_b) == int
        return max(val_a, val_b)


class Not(Query):
    def __str__(self):
        return f"no {self.a}"

    def _call(self, path, **kwargs):
        val_a = self.a(path, **kwargs)
        if val_a == None or type(val_a) == bool:
            # False or None -> inf
            return inf
        if type(val_a) == int:
            # int -> False
            return False


class Before(Query):
    def __str__(self):
        return f"({self.a} . {self.b})"

    def __init__(self, a, b):
        super().__init__(a, b)
        if not isinstance(a, Query) or not isinstance(b, Query):
            return
        for p in a.parameters:
            if p in self.conflicts:
                self.conflicts[p].update(b.parameters)
            else:
                self.conflicts[p] = set(b.parameters)

    def _call(self, path, **kwargs):
        val_a = self.a(path, **kwargs)
        val_b = self.b(path, **kwargs)
        if not type(val_a) == int:
            return val_a
        if not type(val_b) == int:
            return val_b

        if val_a < val_b:
            return val_b
        else:
            return False


class QuerySemantics:
    def __init__(self):
        self.parameters = {}

    def parameter(self, ast):
        p = ast
        if p not in self.parameters:
            self.parameters[p] = Occurs(p)
        return self.parameters[p]

    def And(self, ast):
        return ast.left & ast.right

    def Or(self, ast):
        return ast.left | ast.right

    def Before(self, ast):
        return ast.left < ast.right

    def Not(self, ast):
        return ~ast.right


def extensions(U, path: Path, **kwargs):
    """Generate path extensions"""
    default_kwargs = {
        "by_degree": False,
        "reduction": True,
        "safe": False,
        "debug": False,
    }
    kwargs = {**default_kwargs, **kwargs}

    def sort(p):
        return p.name if not kwargs["by_degree"] else len(U.tangle.incompatible[p])

    ps = possibilities(U, path.events)
    if kwargs["debug"]:
        print(f"possibilities: {ps}")

    if kwargs["safe"]:
        safe_events = U.tangle.safe(ps, path.events)
        if safe_events:
            return {path.extend(min(safe_events, key=sort))}

    if not kwargs["reduction"]:
        return {path.extend(p) for p in ps}
    else:
        parts = partition(U.tangle.incompatible, ps)
        if kwargs["debug"]:
            print(f"parts: {parts}")
        branches = {min(p, key=sort) for p in parts}
        if kwargs["debug"]:
            print(f"branches: {branches}")
        return {path.extend(b) for b in branches}


def match_paths(U, query, yield_xs=False, max_only=False, **kwargs):
    """Yield paths that match query"""
    new_paths = [Path.create_empty()]
    default_kwargs = {"prune": False}
    kwargs = {**default_kwargs, **kwargs}

    if isinstance(query, str):
        query = precedence.parse(query, semantics=QuerySemantics())

    if isinstance(U, Protocol):
        U = UoD.from_protocol(U, conflicts=query.conflicts)

    if kwargs.get("debug"):
        print(f"incompatible: {U.tangle.incompatible}")

    while new_paths:
        path = new_paths.pop()

        if kwargs.get("verbose"):
            print(path.events)
        result = query(path, **kwargs)
        if kwargs.get("verbose"):
            print(result)
        if result != None and not max_only:
            # only yield paths matching the query, not those that return False
            if type(result) == int:
                yield (path, result) if yield_xs else path
            if kwargs["prune"] and result != inf:
                # Don't extend paths that resolve query; infs are indefinite
                continue

        xs = extensions(U, path, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            if result == inf:
                yield (path, inf) if yield_xs else path
            elif max_only and type(result) == int:
                yield (path, result) if yield_xs else path


def deadwood(protocol):
    """Find any messages which are never sent."""
    deadwood = set(protocol.messages.values())
    for p in max_paths(protocol):
        deadwood = deadwood.difference(e.msg for e in p)
    return deadwood
