"""
This agent generates unique labels for orders upon request.
"""

import logging
import uuid
from bspl.adapter import Adapter
from configuration import systems, agents
from Logistics import Labeled, RequestLabel

adapter = Adapter("Labeler", systems, agents)

logger = logging.getLogger("labeler")
logger.setLevel(logging.INFO)

@adapter.reaction(RequestLabel)
async def label(msg):
    """Handles label requests by generating a unique UUID-based label."""
    label = str(uuid.uuid4())
    logger.info(f"Generated label {label} for order {msg['orderID']}")
    await adapter.send(Labeled(label=label, **msg.payload))
    return msg

if __name__ == "__main__":
    logger.info("Starting Labeler...")
    adapter.start()
