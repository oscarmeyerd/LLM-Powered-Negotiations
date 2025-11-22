"""
This agent handles shipping requests by managing delivery logistics and tracking.
It processes shipping requests from sellers and delivers items to buyers.
"""

import logging
import random
import asyncio

from bspl.adapter import Adapter
from configuration import systems, agents
from Purchase import ship, deliver
from bspl.adapter.schema import instantiate

adapter = Adapter("Shipper", systems, agents)
logger = logging.getLogger("shipper")

make_msg = instantiate(adapter) # Instantiating schema variables for future messaging.

# Zone definition and failuire reasons as defined in assignment.
zones = {
    "123 Main St": {"zone": "Local",   "min": 1, "max": 2, "success": 0.98},
    "456 Oak Ave": {"zone": "Regional","min": 2, "max": 4, "success": 0.95},
    "789 Pine Rd": {"zone": "Remote",  "min": 3, "max": 7, "success": 0.90},
}
failure_reasons = ["address_not_found", "recipient_unavailable", "damaged_in_transit", "weather_delay"]

# Counters
shipments_received = 0
deliveries_attempted = 0
deliveries_successful = 0
deliveries_failed = 0

# Zone tracking for success & failure tracking.
zone_stats = {z["zone"]: {"attempts": 0, "success": 0, "fail": 0} for z in zones.values()}

# Reaction for ship msg from seller.
@adapter.reaction(ship)
async def on_ship(msg):
    global shipments_received, deliveries_attempted, deliveries_successful, deliveries_failed
    # Extracting data from the message.
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    addr = msg["address"]
    # Delivery zone lookup from provided address.
    z = zones.get(addr, {"zone": "Unknown", "min": 3, "max": 7, "success": 0.85})
    zone_name = z["zone"]
    # Increment shipment and zone counters.
    shipments_received += 1
    zone_stats[zone_name]["attempts"] = zone_stats.get(zone_name, {"attempts":0}).get("attempts", 0) + 1
    # Proc time and wait.
    processing_time = random.uniform(0.5, 1.5)
    await asyncio.sleep(processing_time)
    # Determining shipping days and converting to delay for sleep.
    delivery_days = random.randint(z["min"], z["max"])
    delivery_delay = delivery_days * 0.2
    logger.info(f"Ship {shortID}: {item} to {addr} ({zone_name} zone, {delivery_days} days)")
    await asyncio.sleep(delivery_delay)
    # increment following delivery outgoing.
    deliveries_attempted += 1
    # Random evaluation for success/failure. Creates and sends messages, increments counters, documents reason, etc. for both cases.
    if random.random() <= z["success"]:
        logger.info(f"Delivery SUCCESS {shortID}: {item} delivered to {addr}")
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome="delivered")
        await adapter.send(d)
        deliveries_successful += 1
        zone_stats[zone_name]["success"] = zone_stats[zone_name].get("success", 0) + 1
    else:
        reason = random.choice(failure_reasons)
        logger.info(f"Delivery FAILED {shortID}: {item} - {reason}")
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome=reason)
        await adapter.send(d)
        deliveries_failed += 1
        zone_stats[zone_name]["fail"] = zone_stats[zone_name].get("fail", 0) + 1
# Final shipping statistics.
async def shipper_stats():
    logger.info("== FINAL SHIPPING STATUS ===")
    logger.info(f"Shipments received: {shipments_received}")
    logger.info(f"Deliveries attempted: {deliveries_attempted}")
    if deliveries_attempted:
        rate = (deliveries_successful / deliveries_attempted) * 100.0
    else:
        rate = 0.0
    logger.info(f"Success rate: {rate:.1f}%")
# Same syntax as buyer and seller.
async def main():
    await asyncio.sleep(10)
    await shipper_stats()

if __name__ == "__main__":
    logger.info("Starting Shipper...")
    adapter.start(main())
    

    