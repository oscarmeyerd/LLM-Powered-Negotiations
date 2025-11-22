from importlib.util import find_spec
from ttictoc import Timer
from .paths import (
    handle_safety,
    handle_liveness,
    handle_paths,
    handle_all,
    max_paths,
    UoD,
)
from .mambo import match_paths, deadwood
from ..generators.mambo import nonlive, unsafe
from ..parsers.bspl import load_protocols
from pprint import pformat

HAS_SAT = find_spec("boolexpr") is not None

if HAS_SAT:
    from .sat import SATCommands


class MamboCommands:
    def liveness(self, *files):
        """Check liveness properties for each protocol in FILES"""
        for protocol in load_protocols(files):
            print(f"{protocol.name} ({protocol.path}):")
            t = Timer()
            t.start()
            q = nonlive(protocol)
            result = next(
                match_paths(protocol, q, residuate=True, incremental=True, prune=True),
                [],
            )
            elapsed = t.stop()
            if result:
                print({"elapsed": elapsed, "live": False, "path": result})
            else:
                print({"elapsed": elapsed, "live": True})

    def safety(self, *files):
        """Check safety properties for each protocol in FILES"""
        for protocol in load_protocols(files):
            print(f"{protocol.name} ({protocol.path}):")
            t = Timer()
            t.start()
            q = unsafe(protocol)
            if not q:
                print({"elapsed": t.stop(), "safe": True, "query": q})
                continue
            result = next(
                match_paths(protocol, q, residuate=True, incremental=True, prune=True),
                [],
            )
            elapsed = t.stop()
            if result:
                print({"elapsed": elapsed, "safe": False, "query": q, "path": result})
            else:
                print({"elapsed": elapsed, "safe": True, "query": q})

    def query(self, path, query):
        for protocol in load_protocols([path]):
            print(f"{protocol.name} ({protocol.path}):")
            paths = [
                str(p.events)
                for p in match_paths(
                    protocol, query, residuate=True, incremental=True, prune=True
                )
            ]
            if paths:
                print("\n".join(paths))
            else:
                print("No matching enactments")

    def deadwood(self, *files):
        for protocol in load_protocols(files):
            t = Timer()
            t.start()
            print(f"{protocol.name} ({protocol.path}):")
            dead = deadwood(protocol)
            elapsed = t.stop()
            print({"deadwood": dead, "elapsed": elapsed})


class Verify:
    def __init__(self):
        self.safety = handle_safety
        self.liveness = handle_liveness
        self.all = handle_all
        self.paths = handle_paths
        self.mambo = MamboCommands()
        if HAS_SAT:
            self.sat = SATCommands()

    def unbound(self, *files):
        """Find any parameters which are never bound."""
        for protocol in load_protocols(files):
            print(f"{protocol.name} ({protocol.path}): ")
            unbound = set(p.name for p in protocol.parameters.values())
            for p in max_paths(protocol):
                unbound = unbound.difference(param for e in p for param in e.msg.outs)
            print(unbound)

    def unused(self, *files):
        """Find any parameters which are bound but never used ('in' in another message)."""
        for protocol in load_protocols(files):
            print(f"{protocol.name} ({protocol.path}): ")
            unused = set()
            for p in max_paths(protocol):
                for e in p:
                    unused.update(e.msg.outs)
            for p in max_paths(protocol):
                for e in p:
                    unused.difference_update(e.msg.ins)
                    unused.difference_update(e.msg.nils)
            print(unused)

    def solitary(self, *files):
        """Find any parameters which only appear once."""
        for protocol in load_protocols(files):
            print(f"{protocol.name} ({protocol.path}): ")
            uses = {p: set() for p in protocol.parameters}
            for p in uses:
                for m in protocol.messages.values():
                    if p in m.parameters:
                        uses[p].add(m)

            solo = set(p for p in uses if len(uses[p]) == 1)
            print(solo)

    def tangle(self, *files, debug=False):
        """Display the tangle for each protocol, showing enables, disables, and tangles relationships."""
        for protocol in load_protocols(files):
            print(f"\n{protocol.name} ({protocol.path}):")
            print("=" * 60)

            # Create UoD and get the tangle graph
            uod = UoD.from_protocol(protocol, debug=debug)
            tangle = uod.tangle

            # Print emissions (sorted by sender name, then message name)
            print("\nEmissions:")
            for e in sorted(tangle.emissions, key=lambda x: (x.sender.name, x.msg.name)):
                print(f"  {e.sender.name}!{e.msg.name}")

            # Print receptions (sorted by recipient name, then message name)
            print("\nReceptions:")
            for r in sorted(tangle.receptions, key=lambda x: (x.recipient.name, x.msg.name)):
                print(f"  {r.recipient.name}?{r.msg.name}")

            # Print endowment relationships
            print("\nEndows relationships:")
            for src, dests in sorted(tangle.endows.items(), key=lambda x: str(x[0])):
                if dests:
                    dest_strs = [str(d) for d in sorted(dests, key=str)]
                    print(f"  {src} endows: {', '.join(dest_strs)}")

            # Print enablement relationships
            print("\nEnables relationships:")
            for src, dests in sorted(tangle.enables.items(), key=lambda x: str(x[0])):
                if dests:
                    dest_strs = [str(d) for d in sorted(dests, key=str)]
                    print(f"  {src} enables: {', '.join(dest_strs)}")

            # Print disablement relationships
            print("\nDisables relationships:")
            for src, dests in sorted(tangle.disables.items(), key=lambda x: str(x[0])):
                if dests:
                    dest_strs = [str(d) for d in sorted(dests, key=str)]
                    print(f"  {src} disables: {', '.join(dest_strs)}")

            # Print tangle relationships
            print("\nTangles relationships:")
            for src, dests in sorted(tangle.tangles.items(), key=lambda x: str(x[0])):
                if dests:
                    dest_strs = [str(d) for d in sorted(dests, key=str)]
                    print(f"  {src} tangles with: {', '.join(dest_strs)}")

            # Print incompatibility relationships
            print("\nIncompatible relationships:")
            for src, dests in sorted(
                tangle.incompatible.items(), key=lambda x: str(x[0])
            ):
                if dests:
                    dest_strs = [str(d) for d in sorted(dests, key=str)]
                    print(f"  {src} incompatible with: {', '.join(dest_strs)}")

            # If there are conflicts
            if hasattr(tangle, "conflicts") and tangle.conflicts:
                print("\nParameter conflicts:")
                for src, dests in sorted(
                    tangle.conflicts.items(), key=lambda x: str(x[0])
                ):
                    if dests:
                        dest_strs = [str(d) for d in sorted(dests, key=str)]
                        print(f"  {src} conflicts with: {', '.join(dest_strs)}")
