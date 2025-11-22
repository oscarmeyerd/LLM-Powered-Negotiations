from .message import Message
from bspl import protocol, load_file
import logging

logger = logging.getLogger("bspl")


def instantiate(adapter):
    def inner(schema, *args, **kwargs):
        system = kwargs.pop("system", None)
        if system == None:
            # default to first system
            system = next(
                ID
                for ID, s in adapter.systems.items()
                if s["protocol"] == schema.parent
            )
        payload = schema.construct(*args, **kwargs)
        return Message(schema, payload, adapter=adapter, system=system)

    return inner


def match(schema, message):
    """Construnct instances of schema that match parameters of message"""
    h = schema.adapter.history
    contexts = h.matching_contexts(message)
    candidates = set()
    for c in contexts:
        if (
            h.check_outs(schema, c)
            and all(p in c.bindings for p in schema.ins)
            and not any(p in c.bindings for p in schema.nils)
        ):
            candidates.add(
                schema(
                    system=message.system,
                    **{p: c.bindings[p] for p in schema.parameters if p in c.bindings}
                )
            )
    return candidates
