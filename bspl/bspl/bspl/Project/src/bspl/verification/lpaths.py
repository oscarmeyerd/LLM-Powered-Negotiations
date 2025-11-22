from ..langshaw import Action, Langshaw
from pprint import pformat
from ttictoc import Timer


def empty_path():
    """The empty path is a list with no message instances"""
    return tuple()


def key_sets(path):
    keys = set()
    for a in path:
        keys.add(tuple(a.keys))
    return keys


def known(path, keys):
    """Compute the set of parameters in social state after enacting path"""

    parameters = {
        p for a in path for p in a.parameters if set(a.keys).intersection(set(keys))
    }
    actions = {a.name for a in path if set(a.keys).intersection(set(keys))}
    return parameters.union(actions)


def attemptable(path, action):
    if action in path:
        return False

    k = known(path, action.keys)

    # all direct dependencies must have already occurred
    for d in action.explicit_dependencies:
        if d not in path:
            return False

    # parameters must be known, or actor must have sayso
    result = all(
        p in k or action.parent.can_bind(action.actor, p) for p in action.parameters
    )
    return result


def unsocial(path, action):
    "An action is unsocial if it conflicts with any prior actions"
    for a in path:
        if action.parent.conflicting(a, action):
            return True
        if action.parent.prevents(a, action):
            return True
    return False


def fits(a, b):
    "Whether a and b agree on their shared keys. In our abstract simulation, this is assumed to be true."
    return True


def disables(protocol, a, b):
    "Return true if action a directly disables action b"

    # a disables b if there's a conflict between them
    # only if they have the same actor
    if protocol.conflicting(a, b) and a.actor == b.actor:
        return True
    if protocol.prevents(a, b) and a.actor == b.actor:
        return True

    # a disables b if they share parameter p where a's actor has sayso
    for p in a.parameters:
        if p in b.parameters:
            if not a.actor in protocol.priorities(
                p
            ) or not b.actor in protocol.priorities(p):
                continue

            a_sayso = protocol.priorities(p).index(a.actor)
            b_sayso = protocol.priorities(p).index(b.actor)
            # lower means it has sayso first
            if a_sayso < b_sayso:
                return True


def enables(path, a, b):
    """
    Return true if action a directly enables action b, given a path
    Implements rule Enable"""

    # an action cannot enable itself
    if a == b:
        return False

    # for some parameter in both a and b
    for p in set(a.parameters).intersection(set(b.parameters)):
        if p in known(path, a.keys):
            # don't consider parameters that are already known
            continue
        if p in a.parent.autonomy_parameters:
            # autonomy parameters indicate direct dependencies on other actions; can't enable anything
            continue
        # actor for a has sayso over parameter
        if a.parent.can_bind(a.actor, p):
            # actor for b does not have sayso over that parameter
            if not a.parent.can_bind(b.actor, p):
                return True

    # autonomy parameters indicate direct dependencies on other actions
    if a.autonomy_parameter in b.parameters:
        return True


def block(a, b):
    """
    a blocks b if nogo(a,b) or nono(a,b)
    """
    protocol = a.parent
    return protocol.conflicting(a, b) or protocol.prevents(a, b)


def dominates(path, a, b):
    """
    a dominates b on path if:
      1. for some p in both
      2. p is not in path
      3. a's actor has priority (higher sayso) over b's actor
    """
    # for p in both a and b
    for p in set(a.parameters).intersection(set(b.parameters)):
        if p in known(path, a.keys):
            # skip known parameters
            continue

        # return true if a's actor has priority over b's
        if a.parent.has_priority(a.actor, b.actor, p):
            return True


def hampers(path, actions):
    """
    Return a graph representation (dict) of entanglements between actions
      actions: a set of actions that are feasible for the next step of path
      path: a sequence of actions
    """
    enablers = {a: {b for b in actions if enables(path, a, b)} for a in actions}

    # propagate enablements; a |- b & b |- c => a |- c
    def enablees(a, seen=set()):
        es = enablers[a]
        return es.union(*[enablees(b, seen.union(es)) for b in es if b not in seen])

    # Rule: Chain
    for a, es in enablers.items():
        es.update(enablees(a))

    # build graph of hampering relationships
    graph = {a: set() for a in actions}

    for a in actions:
        for b in actions:
            if a == b:
                continue
            # Rule: Block
            if a.parent.conflicting(a, b) or a.parent.prevents(a, b):
                graph[a].add(b)

            # Rule: Delay
            elif dominates(path, a, b):
                graph[a].add(b)

    # Rule: Future
    for a in graph:
        # exclude a and known hampered messages from consideration
        for b in actions - graph[a] - set([a]):
            for c in set(graph[a]):
                if b == c:
                    continue
                # a hampers c and b enables c -> a hampers b
                if enables(path, b, c):
                    graph[a].add(b)

    # ensure graph is symmetric
    for a in graph:
        # b is in a's hampered set
        for b in graph[a]:
            # ensure a is in b's hampered set
            graph[b].add(a)

    return graph


class UoD:
    def __init__(self, protocol, **kwargs):
        self.protocol = protocol
        self.actions = set(protocol.actions)
        self.roles = set(protocol.roles)

    def __add__(self, other):
        return UoD(self.actions.union(other.actions), self.roles.union(other.roles))


def feasible(U, path):
    "The set of feasible actions"
    return {a for a in U.actions if attemptable(path, a) and not unsocial(path, a)}


class Color(set):
    def __hash__(self):
        return id(self)


def partition(path, actions, fs):
    """
    Partition a graph of feasible messages into colored sets.
      graph: a dictionary from a vertex (action) to its set of neighbors (those it hampers)
      fs: a list of feasible messages"""

    # alias graph to neighbors for readability
    neighbors = hampers(path, actions)

    def degree(m):
        return len(neighbors[m])

    # Sort vertices by degree in descending order
    vs = sorted(fs, key=degree, reverse=True)

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


def concurrent(path, actions):
    """
    Return sets of feasible actions that can be enacted concurrently
    """
    conc_map = {}
    for a in actions:
        conc_a = set([a])
        for b in actions:
            # different actors, have conflict, neither dominates
            if (
                a.actor != b.actor
                and a.parent.conflicting(a, b)
                and not dominates(path, a, b)
                and not dominates(path, b, a)
            ):
                conc_a.add(b)
        if len(conc_a) > 1:
            # only add nonempty sets
            conc_map[a] = conc_a

    # compact to viable sets
    concs = []
    for a in conc_map:
        # copy set
        conc = set(conc_map[a])
        for b in conc_map[a]:
            conc.intersection_update(conc_map[b])
        # only keep unique sets
        if conc not in concs:
            concs.append(conc)
    return concs


def extensions(U, path, **kwargs):
    default_kwargs = {
        "by_degree": False,
        "reduction": True,
        "debug": False,
    }
    kwargs = {**default_kwargs, **kwargs}
    fs = feasible(U, path)
    if kwargs["debug"]:
        print(f"feasible: {fs}")
    if not kwargs["reduction"]:
        # all feasible actions are extensions
        xs = {path + (p,) for p in fs}
    else:
        parts = partition(path, U.actions, fs)
        concs = concurrent(path, fs)
        if kwargs["debug"]:
            print(f"parts: {parts}")
            print(f"concurrent: {concs}")
        xs = {path + tuple(conc) for conc in concs}.union(
            {path + tuple([p.pop()]) for p in parts}
        )
    return xs


def max_paths(U, **kwargs):
    default_kwargs = {
        "by_degree": False,
        "reduction": True,
        "debug": False,
    }
    kwargs = {**default_kwargs, **kwargs}
    max_paths = []
    new_paths = [empty_path()]
    while len(new_paths):
        p = new_paths.pop()
        xs = extensions(U, p, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            max_paths.insert(len(max_paths), p)
    return max_paths


def complete(U, path):
    "A path is complete when it satisfies the protocol's what clause"
    actions = {a.name for a in path}
    for clause in U.protocol.what:
        satisfied = False
        for p in clause:
            # a clause is satisfied if any parameter is known
            # or represents an action that occurred
            if p["name"] in total_knowledge(U, path) or p["name"] in actions:
                satisfied = True
        # if any clause is unsatisfied, the protocol is incomplete
        if satisfied == False:
            return False
    # if no clause is unsatisfied the protocol is complete
    return True


def liveness(protocol, **kwargs):
    default_kwargs = {"debug": False, "verbose": False}
    kwargs = {**default_kwargs, **kwargs}
    t = Timer()
    t.start()
    U = UoD(protocol, **kwargs)
    new_paths = [empty_path()]
    checked = 0
    max_paths = 0
    while len(new_paths):
        p = new_paths.pop()
        if kwargs["debug"]:
            print(p)
        checked += 1
        xs = extensions(U, p, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            max_paths += 1
            if kwargs["verbose"] and not kwargs["debug"]:
                print(p)
            if not complete(U, p):
                return {
                    "live": False,
                    "reason": "Found path that does not extend to completion",
                    "path": p,
                    "checked": checked,
                    "maximal paths": max_paths,
                    "elapsed": t.stop(),
                }
    return {
        "live": True,
        "checked": checked,
        "maximal paths": max_paths,
        "elapsed": t.stop(),
    }


def safety(protocol, **kwargs):
    default_kwargs = {"debug": False, "verbose": False}
    kwargs = {**default_kwargs, **kwargs}
    t = Timer()
    t.start()
    U = UoD(protocol)
    new_paths = [empty_path()]
    checked = 0
    max_paths = []
    while len(new_paths):
        path = new_paths.pop()
        if kwargs["debug"]:
            print(path)
        checked += 1
        xs = extensions(U, path, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            max_paths.append(path)
            if kwargs["verbose"] and not kwargs["debug"]:
                print(path)

    # safety violated when two or more conflicting actions occur on the same path
    for p in max_paths:
        actions = {a.name for a in p}
        for c in protocol.conflicts:
            if len(set(c).intersection(actions)) > 1:
                return {
                    "safe": False,
                    "reason": "Found path with conflicting actions",
                    "path": p,
                    "checked": checked,
                    "maximal paths": len(max_paths),
                    "elapsed": t.stop(),
                }

    return {
        "safe": True,
        "checked": checked,
        "maximal paths": len(max_paths),
        "elapsed": t.stop(),
    }


def total_knowledge(U, path):
    k = set()
    for keys in key_sets(path):
        k.update(known(path, keys))
    return k


def all_paths(U, **kwargs):
    default_kwargs = {"debug": False, "verbose": False}
    kwargs = {**default_kwargs, **kwargs}
    t = Timer()
    t.start()
    paths = set()
    new_paths = [empty_path()]
    longest_path = 0
    max_paths = 0
    while new_paths:
        p = new_paths.pop()
        if kwargs["debug"]:
            print(p)
        if len(p) > longest_path:
            longest_path = len(p)
        if len(p) > len(U.actions) * 2:
            print("Path too long: ", p)
            exit(1)
        xs = extensions(U, p, **kwargs)
        if xs:
            new_paths.extend(xs)
        else:
            max_paths += 1
            if kwargs["verbose"] and not kwargs["debug"]:
                print(p)

        paths.add(p)  # add path to paths even if it has unreceived messages
    print(
        f"{len(paths)} paths, longest path: {longest_path}, maximal paths: {max_paths}, elapsed: {t.stop()}"
    )
    return paths


def handle_all_paths(
    *files, debug=False, verbose=False, external=False, safe=True, reduction=False
):
    """
    Compute all paths for each protocol

    By default, this does *not* use partial-order reduction, but it can be enabled via the --reduction flag.

    Args:
      files: Paths to specification files containing one or more protocols
      verbose: Enable detailed output
      debug: Print debugging information
      external: Enable external source information
      reduction: Enable reduction
      safe: If reduction is enabled, use heuristic to avoid branching on events assumed to be safe (default True); use --nosafe to disable
    """
    for protocol in load_protocols(files):
        print(f"{protocol.name} ({protocol.path}): ")
        U = UoD.from_protocol(protocol)
        all_paths(
            U,
            verbose=verbose,
            debug=debug,
            external=external,
            safe=safe,
            reduction=reduction,
        )


def handle_liveness(
    *files, verbose=False, debug=False, external=False, safe=True, reduction=True
):
    """
    Compute whether each protocol is live, using path simulation

    By default, this uses tableau-based partial order reduction to minimize the number of paths considered.

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
            liveness(
                protocol,
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
    """
    Compute whether each protocol is safe, using path simulation

    By default, this uses tableau-based partial order reduction to minimize the number of paths considered.

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
            safety(
                protocol,
                verbose=verbose,
                debug=debug,
                external=external,
                safe=safe,
                reduction=reduction,
            )
        )
