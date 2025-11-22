"""
This agent initiates the logistics protocol by generating orders and handling packed responses.
"""

import logging
import random
import asyncio
from bspl.adapter import Adapter
from configuration import systems, agents
from Logistics import RequestLabel, RequestWrapping, Packed

adapter = Adapter("Merchant", systems, agents)

logger = logging.getLogger("merchant")
# logger.setLevel(logging.DEBUG)

async def order_generator():
    """Generates sample orders with random items and addresses."""
    for orderID in range(10):
        await adapter.send(
            RequestLabel(
                orderID=orderID,
                address=random.choice(["Lancaster University", "NCSU"]),
            )
        )
        for i in range(2):
            await adapter.send(
                RequestWrapping(
                    orderID=orderID,
                    itemID=i,
                    item=random.choice(["ball", "bat", "plate", "glass"]),
                )
            )
        await asyncio.sleep(0)

@adapter.reaction(Packed)
async def packed(msg):
    """Handles packed items by logging their status."""
    logger.info(f"Order {msg['orderID']} item {msg['itemID']} packed with status: {msg['status']}")
    return msg

if __name__ == "__main__":
    logger.info("Starting Merchant...")
    adapter.start(order_generator())
