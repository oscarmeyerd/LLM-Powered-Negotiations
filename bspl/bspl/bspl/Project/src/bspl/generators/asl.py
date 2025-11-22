import os
from ..parsers.bspl import load_file
from ..verification import paths
from ..verification.paths import max_paths, UoD, Emission, Reception
from ..utils import abort, camel_to_snake, camel, upcamel


def generate_asl(
    path,
    role=None,
    protocol: str = None,
    roles: list = None,
    dir: str = None,
    out: str = None,
    all_roles: bool = None,
    stdout: bool = False,
    dry: bool = False,
):
    # dict of {role: [goals]}
    goals = {}

    if roles and out:
        abort("Can't specify filename for multiple roles")
    if all_roles and out:
        abort("Can't specify filename for multiple roles")

    spec = load_file(path)
    if protocol:
        ps = [spec.protocols[protocol]]
    else:
        ps = spec.protocols.values()

    for p in ps:
        u = UoD.from_protocol(p, external=True)
        paths = max_paths(u)
        if stdout:
            print(f"#----- Protocol {p.name} ({path}): -----#")
        if role:
            # working with a single role
            roles = [p.roles[role]]
            out = out or role + ".asl"
        elif all_roles:
            # all roles
            roles = [r for r in p.roles.values()]
        elif roles:
            # multiple specified roles
            roles = [p.roles[r] for r in roles]
        else:
            abort(
                "You must identify some role(s) to generate code for, or use --all_roles"
            )
        for r in roles:
            if r not in goals:
                goals[r] = []
            covers = generate_covers(p, r, u, paths)
            covers = {m: [prune(m, c) for c in covers[m]] for m in covers}
            conflicts = identify_conflicts(p, r, u)
            new_goals = generate_goals(covers, conflicts)
            print(f"New goals for {r.name}: ", *new_goals, sep="\n")
            goals[r].extend(new_goals)

    for r in roles:
        if dir and out:
            fp = dir + "/" + out
        elif dir:
            fp = dir + "/" + r.name + ".asl"
        elif out:
            fp = "./" + out
        else:
            fp = "./" + r.name + ".asl"

        if stdout:
            print(f"  #----- Goals for {r.name}: -----#")
            for g in goals[r]:
                print(g)
            # go to the next role, without writing to a file
            continue

        if dry:
            # print where it *would* have been saved
            print(fp)
            # don't save it
            continue

        # Extract the directory path
        dir_path = os.path.dirname(fp)

        # Create the directory if it doesn't already exist
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        with open(fp, "w") as f:
            print(f"Writing {r.name}'s goals to {fp}")
            for g in goals[r]:
                f.write(f"{g}\n")


def generate_covers(protocol, role, uod=None, ps=None):
    """For each emission by ROLE in PROTOCOL, generate a list of covers for that emission.
    Each cover is a set of messages that must be received before the emission can be sent.
    """
    u = uod or UoD.from_protocol(protocol, external=True)
    ps = ps or max_paths(u)
    # Convert generator to list to avoid consumption issue
    ps = list(ps)
    covers = {}
    for e in role.emissions(protocol):
        covers[e] = []
        # the list of paths that include the target emission e
        inclusive_ps = [p for p in ps if e in paths.emissions(p)]
        for p in inclusive_ps:
            cover = set()
            ins = set(e.ins)  # need to track ins for current cover
            for ev in p:
                m = ev.msg
                if m != e:
                    intersection = ins.intersection(m.ins.union(m.outs))
                    if intersection and m in role.observations(protocol):
                        cover.add(m)
                        for i in ins.intersection(m.parameters.keys()):
                            ins.discard(i)
                if not ins and cover not in covers[e]:
                    covers[e].append(cover)
                    break
    return covers


def prune(emission, cover):
    """Prune a cover by removing messages whose portion of the emission's 'in' parameters are fully covered by other messages in the cover"""
    pruned = set()

    for m in cover:
        if not any(
            emission.ins.intersection(m.ins.union(m.outs))
            <= other.ins.union(other.outs)
            for other in cover
            if other != m
        ):
            pruned.add(m)
    return pruned


def msg_prefix(message):
    return [
        "MasID",
        message.sender.name.capitalize(),
        message.recipient.name.capitalize(),
    ]


def msg_term(message):
    msg_params = ", ".join(
        msg_prefix(message)
        + [
            upcamel(param)
            for param in message.parameters
            if message.public_parameters[param].adornment in ("in", "out")
        ]
    )
    return f"{camel_to_snake(message.name)}({msg_params})"


def identify_conflicts(protocol, role, u=None):
    """
    Identify conflicts for each message a role can emit.

    Args:
        protocol: The protocol containing the messages
        role: The role checking for conflicts
        u: The UoD object (optional for performance, will be created if not provided)

    Returns:
        A dictionary mapping messages to their conflicts
    """
    conflicts = {}
    u = u or UoD.from_protocol(protocol, external=True)

    for message in role.emissions(protocol):
        conflicts[message] = []

        # Check each message observable by the role
        for o in role.observations(protocol):
            if o == message:
                continue  # Skip the message itself

            # Check if the observed message has parameters that conflict
            if (
                role == o.sender
                and Emission(message) in u.tangle.disables[Emission(o)]
                or role == o.recipient
                and Emission(message) in u.tangle.disables[Reception(o)]
            ):
                conflicts[message].append(o)

    return conflicts


def generate_goals(covers, conflicts={}):
    """
    Generate AgentSpeak goals for a role based on message covers.

    Args:
        covers: Dictionary mapping messages to sets of cover messages
        role: The role generating goals for
        protocol: The protocol containing the messages

    Returns:
        A list of AgentSpeak goals/plans
    """
    goals = []

    for message, cover_sets in covers.items():
        # Create message parameters string for goal invocation
        msg_params = ", ".join(
            msg_prefix(message)
            + [upcamel(param) for param in message.parameters if param in message.ins]
        )

        # Create goal name to send the message
        msg_goal = f"!send_{camel_to_snake(message.name)}({msg_params})"

        # Create comment for out parameter computation
        msg_comment = f"// insert code to compute {message.name} out parameters {sorted(message.outs)} here\n    "

        # Create conflict guards - prevent execution if conflicting messages exist
        conflict_guards = [
            f"not {msg_term(conflict)}" for conflict in conflicts.get(message, [])
        ]

        for cover in cover_sets:
            if len(cover) == 0:
                # Case 1: No dependencies - create direct plan with conflict guards
                plan = f"+!send_{camel_to_snake(message.name)}"
                if conflict_guards:
                    plan += f"\n  : {' & '.join(conflict_guards)}"
                plan += f"\n  <- {msg_comment} .emit({msg_term(message)}).\n"
                goals.append(plan)

            elif len(cover) == 1:
                # Case 2: Single dependency - trigger on that message with conflict guards
                dep_message = list(cover)[0]
                plan = f"+{msg_term(dep_message)}"
                if conflict_guards:
                    plan += f"\n  : {' & '.join(conflict_guards)}"
                plan += f"\n  <- {msg_comment} .emit({msg_term(message)}).\n"
                goals.append(plan)

            else:
                # Case 3: Multiple dependencies - create plans with guards
                for dep_message in cover:
                    # Create context conditions for other dependencies
                    other_deps = [other for other in cover if other != dep_message]
                    context = " & ".join([msg_term(other) for other in other_deps])

                    # Add conflict guards to context
                    if conflict_guards:
                        if context:
                            context += " & " + " & ".join(conflict_guards)
                        else:
                            context = " & ".join(conflict_guards)

                    goals.append(
                        f"+{msg_term(dep_message)}\n  : {context}\n  <- {msg_goal}.\n"
                    )

                # Add the plan for the message goal with conflict guards
                plan = f"+{msg_goal}"
                if conflict_guards:
                    plan += f"\n  : {' & '.join(conflict_guards)}"
                plan += f"\n  <- {msg_comment} .emit({msg_term(message)}).\n"
                goals.append(plan)

    return goals
