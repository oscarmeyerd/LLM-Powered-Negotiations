from ..protocol import Message, Role, Parameter, Protocol
from pprint import pformat
from ttictoc import Timer
from ..parsers.bspl import load_protocols
from collections.abc import Mapping


def empty_path():
    """The empty path is a list with no message instances"""
    return tuple()


External = Role("*External*")


class Emission:
    def __init__(self, msg):
        self.msg = msg

    def __repr__(self):
        return f"{self.sender.name}!{self.msg.name}"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.msg == other.msg
        else:
            return False

    def __hash__(self):
        return (self.msg).__hash__()

    def __getattr__(self, attr):
        return getattr(self.msg, attr)


def key_sets(path):
    keys = set()
    for i in path:
        keys.add(tuple(i.msg.keys))
    return keys


def known(path, keys, R):
    """Compute the set of parameters observed by role R after enacting path"""
    time = 0
    k = set()
    for instance in path:
        if set(instance.msg.parameters).intersection(set(keys)) and (
            (isinstance(instance, Emission) and instance.sender.name == R.name)
            or (
                isinstance(instance, Reception)
                and R.name in [r.name for r in instance.recipients]
            )
        ):
            k.update(instance.ins)
            k.update(instance.outs)
        time += 1
    return k


def sources(path, p):
    """The set of all roles that produce p as an out parameter in path"""
    return set(i.msg.sender.name for i in path if p in i.msg.outs)


def protocol_has_single_key_context(protocol):
    """Check if all messages in protocol share the same key context"""
    if not protocol.messages:
        return True

    # Get the key context of the first message
    first_msg = next(iter(protocol.messages.values()))
    first_context = tuple(sorted(first_msg.keys.keys()))

    # Check if all other messages have the same key context
    for msg in protocol.messages.values():
        if tuple(sorted(msg.keys.keys())) != first_context:
            return False

    return True


def has_parameter_conflict(path, p):
    """Check if parameter p has conflicting sources within the same key context"""
    # Group message instances by their key context
    contexts = {}
    for i in path:
        if p in i.msg.outs:
            # Create a key context tuple from the message's key parameters
            key_context = tuple(sorted(i.msg.keys.keys()))
            if key_context not in contexts:
                contexts[key_context] = set()
            contexts[key_context].add(i.msg.sender.name)

    # Check if any key context has multiple sources (real conflict)
    for key_context, role_set in contexts.items():
        if len(role_set) > 1:
            return True

    return False


def check_all_parameter_conflicts(path, parameters):
    """Check all parameters for conflicts in a single pass through the path"""
    # Build all key contexts once
    param_contexts = {}  # param -> {key_context -> set(roles)}

    for i in path:
        key_context = tuple(sorted(i.msg.keys.keys()))
        for p in i.msg.outs:
            if p not in param_contexts:
                param_contexts[p] = {}
            if key_context not in param_contexts[p]:
                param_contexts[p][key_context] = set()
            param_contexts[p][key_context].add(i.msg.sender.name)

    # Check for conflicts
    for p, contexts in param_contexts.items():
        for role_set in contexts.values():
            if len(role_set) > 1:
                return p  # Return first conflicting parameter
    return None


def viable(path, msg):
    msg_count = len([i.msg for i in path if i.msg == msg])
    if not msg.outs and msg_count > 0:
        # only allow one copy of an all "in"/"nil" message
        # print("Only one copy of all in message allowed")
        return False
    if msg.sender == External:
        # only send external messages if they would contribute
        k = known(path, (), msg.recipient)
        if not k.issuperset(msg.ins):
            return True
        else:
            print("Only send external messages if they would contribute")
            return False
    out_keys = set(msg.keys).intersection(msg.outs)
    if out_keys and all(sources(path, p) for p in out_keys):
        # don't allow multiple key bindings in the same path; they're different enactments
        # print("Don't allow multiple key bindings on the same path; they're different enactments")
        return False
    k = known(path, msg.keys, msg.sender)
    return k.issuperset(msg.ins) and k.isdisjoint(msg.outs) and k.isdisjoint(msg.nils)


def disables(a, b):
    "Return true if message a directly disables message b"

    if isinstance(a, Emission) and isinstance(b, Emission):
        if a.outs.intersection(a.keys).intersection(b.outs).intersection(b.keys):
            # they both share an out key, and should be in different enactments
            return True
        if a.sender == b.sender:
            for p in a.outs:
                # out disables out or nil
                if p in b.parameters and b.parameters[p].adornment in ["out", "nil"]:
                    return True
    if (
        isinstance(a, Reception)
        and isinstance(b, Emission)
        and b.sender in a.recipients
    ):
        for p in a.outs.union(a.ins):
            # out or in disables out or nil
            if p in b.parameters and b.parameters[p].adornment in ["out", "nil"]:
                return True


def enables(a, b):
    "Return true if message a directly enables message b"
    if isinstance(a, Emission) and isinstance(b, Reception) and a.msg == b.msg:
        # emissions enable their reception
        return True

    if (
        not isinstance(b, Emission)
        or (isinstance(a, Emission) and a.sender != b.sender)
        or (isinstance(a, Reception) and a.recipient != b.sender)
    ):
        # only emissions can be enabled by other messages, and only at the sender
        return False

    if not disables(a, b):
        # out enables in
        for p in a.outs:
            if p in b.parameters and b.parameters[p].adornment == "in":
                return True


def transitive_closure(graph):
    # Initialize the closure dictionary
    closure = {node: set() for node in graph}

    # Helper function for depth-first search
    def dfs(current_node, start_node, visited):
        # Iterate over all neighbors of the current node
        for neighbor in graph.get(current_node, []):
            if neighbor not in visited:
                # Mark the neighbor as reachable from the start node
                closure[start_node].add(neighbor)
                # Mark the neighbor as visited
                visited.add(neighbor)
                # Recur to find all reachable nodes from this neighbor
                dfs(neighbor, start_node, visited)

    # Loop through each node in the graph and compute the closure
    for node in graph:
        visited = set([node])
        dfs(node, node, visited)

    return closure


class Tangle:
    "Graph representation of entanglements between messages"

    def __init__(self, messages, roles, **kwargs):
        default_kwargs = {"debug": False}
        kwargs = {**default_kwargs, **kwargs}
        self.emissions = {Emission(m) for m in messages}
        # Create separate reception events for each recipient
        self.receptions = set()
        for emission in self.emissions:
            for recipient in emission.recipients:
                self.receptions.add(Reception(emission, recipient))
        self.events = self.emissions.union(self.receptions)

        # setup extra conflicts between parameters
        self.conflicts = {}
        if "conflicts" in kwargs:
            for a in kwargs["conflicts"]:
                for b in kwargs["conflicts"][a]:
                    As = set()
                    Bs = set()
                    for e in self.events:
                        ps = e.ins.union(e.outs)
                        if a in ps and b not in ps:
                            As.add(e)
                        if b in ps and a not in ps:
                            Bs.add(e)
                    for e in As:
                        if e in self.conflicts:
                            self.conflicts[e].update(Bs)
                        else:
                            self.conflicts[e] = Bs

        # sources for parameters, for computing endowment
        self.sources = {}
        for R in roles:
            self.sources[R] = {}
            for e in self.events:
                if (
                    isinstance(e, Emission)
                    and e.sender != R
                    or isinstance(e, Reception)
                    and getattr(e, "recipient", None) != R
                    and R not in e.recipients
                ):
                    continue

                for p in e.outs:
                    if p not in self.sources[R]:
                        self.sources[R][p] = [e]
                    else:
                        self.sources[R][p].append(e)

        # track messages that are the sole source of a given parameter
        self.source = {}
        for R in roles:
            self.source[R] = {
                p: ms[0] for p, ms in self.sources[R].items() if len(ms) == 1
            }

        # a endows b if a is the sole source of an 'in' parameter of b
        self.endows = {e: {Reception(e)} for e in self.emissions}
        for b in self.emissions:
            for p in b.ins:
                a = self.source[b.sender].get(p)
                if not a:
                    continue
                if a in self.endows:
                    self.endows[a].add(b)
                else:
                    self.endows[a] = {b}

        # propagate endowments; a endows b & b endows c => a endows c
        self.endows = transitive_closure(self.endows)

        if kwargs["debug"]:
            print(f"endows: {pformat(self.endows)}")

        # initialize graph with direct enable and disablements, O(m^2)
        self.enables = {
            a: {b for b in self.events if a != b and enables(a, b)} for a in self.events
        }
        self.disables = {
            a: {
                b
                for b in self.events
                if a != b and not a in self.endows.get(b, []) and disables(a, b)
            }
            for a in self.events
        }

        if kwargs["debug"]:
            print(f"disables: {pformat(self.disables)}")
            print(f"enables: {pformat(self.enables)}")

        # propagate enablements; a |- b & b |- c => a |- c
        self.enables = transitive_closure(self.enables)

        # compute entanglements:
        # a tangles c if:
        #  1. a does not endow c
        #  2. a disables c or a disables b and c enables b
        # or a conflicts c or a conflicts b and c enables b
        self.tangles = {
            a: self.disables[a]  # a -| c
            .union(  # or
                {
                    c
                    for c in self.enables
                    if c not in self.endows.get(a, [])  # a does not endow c
                    and self.enables[c].intersection(
                        self.disables[a]
                    )  # a -| b and c |- b
                }
            )
            .union(self.conflicts.get(a, set()))  # merge in conflicts
            .union(
                {
                    c
                    for c in self.enables
                    if c not in self.endows.get(a, [])
                    and self.enables[c].intersection(self.conflicts.get(a, set()))
                }
            )
            for a in self.events
        }

        # initialize incompatibility graph
        self.incompatible = {}
        for e in self.events:
            self.incompatible[e] = set()

        # a and b are incompatible if
        # one tangles with the other
        for a in self.tangles:
            for b in self.tangles[a]:
                self.incompatible[a].add(b)
                self.incompatible[b].add(a)

    def safe(self, possibilities, path):
        ps = possibilities.copy()
        risky = {
            e
            for e in self.events
            if self.disables[e].difference(path)
            or any(e in self.disables[b] for b in self.events)
        }
        return ps.difference(risky)


class UoD:
    def __init__(self, messages=set(), roles={}, **kwargs):
        self.messages = set(messages)
        self.roles = set(roles)
        self.tangle = Tangle(messages, roles, **kwargs)

    @staticmethod
    def from_protocol(protocol, **kwargs):
        if not protocol.ins.union(protocol.nils) or not kwargs.get("external", True):
            # either there are no potential blockers (no ins or nils)
            # or there are, but we aren't generating external sources for them
            return UoD(
                list(protocol.messages.values()), protocol.roles.values(), **kwargs
            )
        else:
            # generate external messages for each role providing the in parameters its messages depend on
            dependencies = {}
            for r in protocol.roles.values():
                if r.name is External.name:
                    continue
                keys = protocol.ins.intersection(protocol.keys)
                # generate messages that provide p to each sender
                msg = Message(
                    f"external->{r.name}",
                    sender=External,
                    recipients=[r],
                    parameters=[Parameter(k, "in", True, parent=protocol) for k in keys]
                    + [
                        Parameter(p, "in", parent=protocol)
                        for p in protocol.ins.difference(keys)
                    ],
                )
                dependencies[r.name] = msg
            # hmmm; probably shouldn't modify protocol...
            protocol.roles[External.name] = External
            uod = UoD(
                list(protocol.messages.values()) + list(dependencies.values()),
                protocol.roles.values(),
                **kwargs,
            )
            return uod

    def __add__(self, other):
        return UoD(self.messages.union(other.messages), self.roles.union(other.roles))


class Reception:
    def __init__(self, emission, recipient=None):
        self.emission = emission
        self.msg = emission.msg
        self._recipient = recipient

    @property
    def recipient(self):
        """Return the specific recipient - explicit if set, otherwise fall back to emission's first recipient"""
        if self._recipient is not None:
            return self._recipient
        # Fall back to first recipient for backward compatibility
        return self.emission.recipients[0] if self.emission.recipients else None

    @property
    def recipients(self):
        """Return recipients - single recipient if specified, otherwise all from emission"""
        if self._recipient is not None:
            return [self._recipient]
        return self.emission.recipients

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.msg == other.msg and self.recipient == other.recipient
        else:
            return False

    def __hash__(self):
        return hash((self.msg, self.recipient))

    def __getattr__(self, attr):
        return getattr(self.emission, attr)

    def __repr__(self):
        if self.recipient is not None:
            return f"{self.recipient.name}?{self.msg.name}"
        else:
            recipients_str = ",".join([r.name for r in self.recipients])
            return f"{recipients_str}?{self.msg.name}"


def emissions(path):
    return [e.msg for e in path if type(e) is Emission]


def unreceived(path):
    sent = set(e for e in path if isinstance(e, Emission))
    received = set(r.emission for r in path if isinstance(r, Reception))
    return sent.difference(received)


def possibilities(U, path):
    b = set()
    for msg in U.messages:
        if viable(path, msg):
            # default messages to unreceived, progressively receive them later
            inst = Emission(msg)
            b.add(inst)
    # Generate separate reception events for each recipient
    receptions = set()
    for emission in unreceived(path):
        for recipient in emission.recipients:
            # Check if this specific recipient already received this emission
            already_received = any(
                isinstance(r, Reception)
                and r.emission == emission
                and getattr(r, "recipient", None) == recipient
                for r in path
            )
            if not already_received:
                receptions.add(Reception(emission, recipient))

    ps = b.union(receptions)
    return ps


def any_unreceived(path):
    return len(unreceived(path)) > 0


class Color(set):
    def __hash__(self):
        return id(self)


def partition(graph, ps):
    """
    Partition a set of possibilities into incompatible subsets.
      graph: a dictionary from a vertex to its set of neighbors
      ps: a list of possibilities"""

    # alias graph to neighbors for readability
    neighbors = graph

    def degree(m):
        return len(neighbors[m])

    # Sort vertices by degree in descending order
    vs = sorted(ps, key=degree, reverse=True)

    parts = set()
    coloring = {}
    for vertex in vs:
        # Assign a color to each vertex that isn’t assigned to its neighbors
        options = parts.difference({coloring.get(n) for n in neighbors[vertex]})

        # generate a new color if necessary
        if len(options) == 0:
            color = Color()
            parts.add(color)
        elif len(options) > 1:
            # Choose a color that
            #  (1) has the highest cardinality (number of vertices)
            max_cardinality = max(len(c) for c in options)
            # print(f"max_cardinality: {max_cardinality}, {[len(o) for o in options]}")
            options = {o for o in options if len(o) == max_cardinality}

            #  (2) within such, the color whose vertex of highest degree has the smallest degree
            if len(options) > 1:

                def max_degree(color):
                    return max(degree(v) for v in color)

                min_max = min(max_degree(o) for o in options)
                options = {o for o in options if max_degree(o) == min_max}

            # choose color from options (randomly?)
            # print(f"options: {len(options)}")
            color = next(o for o in options)
        else:
            color = next(o for o in options)

        # color vertex
        color.add(vertex)
        coloring[vertex] = color

    return parts


def extensions(U, path, **kwargs):
    default_kwargs = {
        "by_degree": False,
        "reduction": True,
        "safe": False,
        "debug": False,
    }
    kwargs = {**default_kwargs, **kwargs}
    if kwargs["debug"]:
        print(f"path: {path}")
    ps = possibilities(U, path)
    safe_events = U.tangle.safe(ps, path)

    # default to selecting branches by message name
    def sort(p):
        return p.name

    if kwargs["by_degree"]:
        # select events by degree instead
        def sort(p):
            return len(U.tangle.incompatible[p])

    if not kwargs["reduction"]:
        # all the possibilities
        xs = {path + (p,) for p in ps}
    elif kwargs["safe"] and safe_events:
        # expand all non-disabling events first
        xs = {path + (min(safe_events, key=sort),)}
    else:
        parts = partition(U.tangle.incompatible, ps)
        if kwargs["debug"]:
            print(f"parts: {parts}")
        branches = {min(p, key=sort) for p in parts}
        if kwargs["debug"]:
            print(f"branches: {branches}")
        xs = {path + (b,) for b in branches}
    return xs


def max_paths(U, yield_xs=False, **kwargs):
    """Yield each path in UoD U that is maximal, i.e., has no extensions."""
    if isinstance(U, Protocol):
        U = UoD.from_protocol(U, **kwargs)

    new_paths = [empty_path()]
    while len(new_paths):
        p = new_paths.pop()
        if "query" in kwargs and kwargs["query"](p) == False:
            continue
        xs = extensions(U, p, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            yield (p, xs) if yield_xs else p


def every_path(U, yield_xs=False, **kwargs):
    """Yield each path in UoD U."""
    if isinstance(U, Protocol):
        U = UoD.from_protocol(U, **kwargs)

    new_paths = [empty_path()]
    while len(new_paths):
        path = new_paths.pop()
        xs = extensions(U, path, **kwargs)
        if xs:
            new_paths.extend(xs)

        yield (path, xs) if yield_xs else path


def verify(protocol, fn, generator=max_paths, **kwargs):
    default_kwargs = {"debug": False, "verbose": False}
    kwargs = {**default_kwargs, **kwargs}
    t = Timer()
    t.start()
    U = UoD.from_protocol(protocol, **kwargs)
    if kwargs["debug"]:
        print(f"incompatibilities: {pformat(U.tangle.incompatible)}")
    state = {}
    count = 0
    for path, xs in generator(U, yield_xs=True, **kwargs):
        count += 1
        if kwargs["verbose"] and not kwargs["debug"]:
            print(path)

        result = fn(U=U, protocol=protocol, path=path, xs=xs, **kwargs)
        # True/False ends with a result, None continues
        if result == None:
            continue
        else:
            return {
                "elapsed": t.stop(),
                "path": path,
                "paths": count,
                **result,
            }

    final = fn(U=U, protocol=protocol, done=True, **kwargs)
    return {
        "elapsed": t.stop(),
        "paths": count,
        **final,
    }


def total_knowledge(U, path):
    k = set()
    for r in U.roles:
        for keys in key_sets(path):
            k.update(known(path, keys, r))
    return k


def liveness(U=None, protocol=None, path=None, done=None, **kwargs):
    if done:
        return {"live": True}

    known = total_knowledge(U, path).intersection(protocol.outs)
    if known < protocol.outs:
        return {"live": False, "incomplete": known.difference(protocol.outs)}


def safety(protocol=None, path=None, done=None, **kwargs):
    if done:
        return {"safe": True}

    parameters = {p for m in protocol.messages.values() for p in m.outs}

    # Use key-aware safety checking
    # Optimization: Check if protocol has single key context
    single_key_context = protocol_has_single_key_context(protocol)

    if single_key_context:
        # Fast path: Use simple sources check for single key context
        for p in parameters:
            if len(sources(path, p)) > 1:
                return {"safe": False, "unsafe": p}
    else:
        # Complex path: Check all parameters in single pass with key context awareness
        conflicting_param = check_all_parameter_conflicts(path, parameters)
        if conflicting_param:
            return {"safe": False, "unsafe": conflicting_param}


def live(p):
    return verify(p, liveness)


def safe(p):
    return verify(p, safety)


def handle_paths(
    *files,
    maximal=False,
    debug=False,
    verbose=False,
    external=False,
    safe=True,
    reduction=False,
    quiet=False,
):
    """Compute all paths for each protocol

    By default, this does *not* use partial-order reduction, but it can be
    enabled via the --reduction flag.

    Args:
      files: Paths to specification files containing one or more protocols
      verbose: Enable detailed output
      debug: Print debugging information
      external: Enable external source information
      reduction: Enable reduction
      safe: If reduction is enabled, use heuristic to avoid branching on events assumed to be safe (default True); use --nosafe to disable
      maximal: Only compute maximal paths; enable with --maximal
    """

    longest_path = []
    paths = []
    maxed = []

    def step(done=None, path=None, xs=None, **kwargs):
        nonlocal longest_path
        if done:
            return {"longest": longest_path, "max-paths": len(maxed)}
        else:
            paths.append(path)
            if len(path) > len(longest_path):
                longest_path = path
            if not xs:
                maxed.append(path)

    for protocol in load_protocols(files):
        print(f"{protocol.name} ({protocol.path}): ")
        print(
            verify(
                protocol,
                step,
                every_path if not maximal else max_paths,
                verbose=verbose,
                debug=debug,
                external=external,
                safe=safe,
                reduction=reduction,
            )
        )


def handle_liveness(
    *files, verbose=False, debug=False, external=False, safe=True, reduction=True
):
    """Compute whether each protocol is live, using path simulation

    By default, this uses tableau-based partial order reduction to minimize
    the number of paths considered.

    Args:
      files: Paths to specification files containing one or more protocols
      verbose: Enable detailed output
      debug: Print debugging information
      external: Enable external source information
      reduction: Enable reduction (default True); use --noreduction to disable
      safe: If reduction is enabled, use heuristic to avoid branching on events assumed to be safe (default True); use --nosafe to disable

    """
    for protocol in load_protocols(files):
        print(f"{protocol.name} ({protocol.path}): ")
        print(
            verify(
                protocol,
                liveness,
                verbose=verbose,
                debug=debug,
                external=external,
                safe=safe,
                reduction=reduction,
            )
        )


def handle_safety(
    *files, verbose=False, debug=False, external=True, safe=True, reduction=True
):
    """Compute whether each protocol is safe, using path simulation

    By default, this uses tableau-based partial order reduction to minimize
    the number of paths considered.

    Args:
      files: Paths to specification files containing one or more protocols
      verbose: Enable detailed output
      debug: Print debugging information
      external: Enable external source information (default True); use --noexternal to disable
      reduction: Enable reduction (default True); use --noreduction to disable
      safe: If reduction is enabled, use heuristic to avoid branching on events assumed to be safe (default True); use --nosafe to disable

    """
    for protocol in load_protocols(files):
        print(f"{protocol.name} ({protocol.path}): ")
        print(
            verify(
                protocol,
                safety,
                every_path,
                verbose=verbose,
                debug=debug,
                external=external,
                safe=safe,
                reduction=reduction,
            )
        )


def handle_all(
    *files, verbose=False, debug=False, external=True, safe=True, reduction=True
):
    """
    Compute whether each protocol is both safe and live, using path simulation

    By default, this uses tableau-based partial order reduction to minimize the number of paths considered.

    Args:
      files: Paths to specification files containing one or more protocols
      verbose: Enable detailed output
      debug: Print debugging information
      external: Enable external source information (default True); use --noexternal to disable
      reduction: Enable reduction (default True); use --noreduction to disable
      safe: If reduction is enabled, use heuristic to avoid branching on events assumed to be safe (default True); use --nosafe to disable
    """
    for file in files:
        try:
            protocols = list(load_protocols([file]))
        except ValueError as e:
            print(f"{file}: Validation error - {e}")
            continue
        except Exception as e:
            print(f"{file}: Parse error - {e}")
            continue

        for protocol in protocols:
            print(f"{protocol.name} ({protocol.path}): ")
            try:
                print(
                    verify(
                        protocol,
                        safety,
                        max_paths,
                        verbose=verbose,
                        debug=debug,
                        external=external,
                        safe=safe,
                        reduction=reduction,
                    )
                )
                print(
                    verify(
                        protocol,
                        liveness,
                        max_paths,
                        verbose=verbose,
                        debug=debug,
                        external=external,
                        safe=safe,
                        reduction=reduction,
                    )
                )
            except Exception as e:
                if debug:
                    raise
                print(f"Verification error: {e}")
                print("(Use --debug flag to see full traceback)")
