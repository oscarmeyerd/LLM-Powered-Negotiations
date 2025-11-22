#!/usr/bin/env python3

from bspl.parsers.bspl import load_file
from bspl.verification.mambo import Occurs, get_smart_name
from itertools import combinations, chain


def has_key_conflict(msg1, msg2):
    """Check if two messages could have a safety conflict based on key contexts."""
    keys1 = set(msg1.keys.keys())
    keys2 = set(msg2.keys.keys())
    return keys1.issubset(keys2) or keys2.issubset(keys1)


def unsafe(protocol):
    sources = {
        p: {m for m in protocol.messages.values() if p in m.outs}
        for p in protocol.parameters
    }
    conflicts = set(tuple(sources[p]) for p in sources if len(sources[p]) > 1)
    if not conflicts:
        return None
    # safety = not ((m1 and m2) or (m3 and m4) ...) for all pairs of conflicting messages
    # compute And(m1, m2) for all pairs of conflicting messages

    pairs = set(chain.from_iterable(combinations(c, 2) for c in conflicts))
    pairs = [
        (Occurs(get_smart_name(protocol.spec, p[0])) & Occurs(get_smart_name(protocol.spec, p[1])))
        for p in pairs
        if p[0].sender != p[1].sender and has_key_conflict(p[0], p[1])
    ]
    if not pairs:
        return None

    # compute disjunction of all pairs
    clause = pairs[0]
    for p in pairs[1:]:
        clause = clause | p
    return clause


def nonlive(protocol):
    outs = list(protocol.outs)
    expr = ~Occurs(outs[0])
    for o in outs[1:]:
        expr = expr | ~Occurs(o)
    return expr


class MamboGenerator:
    def unsafe(self, path, protocol=None):
        spec = load_file(path)
        if protocol:
            Ps = [spec.protocols[protocol]]
        else:
            Ps = spec.protocols.values()

        for P in Ps:
            conjs = unsafe(P)
            if conjs:
                yield f"{P.name}: {conjs}"
            else:
                yield f"{P.name}: safe"

    def nonlive(self, path, protocol=None):
        """Protocols are non-live if any of the out parameters are unbound"""
        spec = load_file(path)
        if protocol:
            Ps = [spec.protocols[protocol]]
        else:
            Ps = spec.protocols.values()

        for P in Ps:
            expr = nonlive(P)
            yield f"{P.name}: {expr}"
