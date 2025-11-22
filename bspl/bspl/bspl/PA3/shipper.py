"""
This agent handles shipping requests by managing delivery logistics and tracking.
It processes shipping requests from sellers and delivers items to buyers.
"""

import logging
import asyncio
import json

from bspl.adapter import Adapter
from configuration import systems, agents
from Purchase import ship, deliver
from bspl.adapter.schema import instantiate
from llm import call_llm
from throttle import Throttle

adapter = Adapter("Shipper", systems, agents)
logger = logging.getLogger("shipper")

make_msg = instantiate(adapter)

# Zone definition and failure reasons
zones = {
    "123 Main St": {"zone": "Local",   "min": 1, "max": 2, "weather": "clear",    "risk": "low"},
    "456 Oak Ave": {"zone": "Regional","min": 2, "max": 4, "weather": "snow",     "risk": "medium"},
    "789 Pine Rd": {"zone": "Remote",  "min": 3, "max": 7, "weather": "blizzard", "risk": "high"},
}
failure_reasons = [
    "address_not_found",
    "recipient_unavailable",
    "damaged_in_transit",
    "weather_delay",
    "capacity_exceeded",
]
# Fleet capacity tracking
capacity = {
    "max_trucks": 6,
    "active_trucks": 0,
    "peak_season": True,
}

# Simulate truck usage
async def occupy_truck(duration: int):
    """Simulate a truck being in use for a given duration (eta_days)."""
    capacity["active_trucks"] += 1
    try:
        await asyncio.sleep(duration * 0.3)  # Simulated day ~0.3s
    finally:
        capacity["active_trucks"] = max(0, capacity["active_trucks"] - 1)
# Check capacity lvls
def has_capacity():
    """Return True if another truck can be assigned."""
    return capacity["active_trucks"] < capacity["max_trucks"]

# Counters
shipments_received = 0
deliveries_attempted = 0
deliveries_successful = 0
deliveries_failed = 0

# Zone stats tracking
zone_stats = {z["zone"]: {"attempts": 0, "success": 0, "fail": 0} for z in zones.values()}
zone_stats.setdefault("Unknown", {"attempts": 0, "success": 0, "fail": 0})

# Helper function to parse and normalize LLM JSON response
def normalize_llm_json(txt: str, base_eta_min: int, base_eta_max: int):
    """Normalize JSON from LLM and default to a safe shipping plan."""
    try:
        data = json.loads(txt)
        if not isinstance(data, dict):
            raise ValueError("Not JSON object")
    except Exception:
        avg = max(base_eta_min, (base_eta_min + base_eta_max) // 2)
        return {
            "decision": "SHIP",
            "service": "standard",
            "eta_days": max(1, avg),
            "outcome": "delivered",
            "reason": "Defaulting due to parsing error",
        }
    # Shipper decisions
    decision = str(data.get("decision", "SHIP")).upper()
    if decision not in ["SHIP", "DELAY", "REJECT"]:
        decision = "SHIP"
    # Shipper service selection
    service = str(data.get("service", "standard")).lower()
    if service not in ["standard", "express", "overnight"]:
        service = "standard"

    try:
        eta_days = int(data.get("eta_days", (base_eta_min + base_eta_max) // 2))
    except Exception:
        eta_days = (base_eta_min + base_eta_max) // 2
    eta_days = max(1, min(max(base_eta_max, 1), eta_days))
    # Shipper outcomes
    outcome = str(data.get("outcome", "delivered"))
    if outcome != "delivered" and outcome not in failure_reasons:
        outcome = "weather_delay" if decision != "SHIP" else "delivered"

    reason = str(data.get("reason", "")).strip()
    # Return results from LLM
    return {
        "decision": decision,
        "service": service,
        "eta_days": eta_days,
        "outcome": outcome,
        "reason": reason,
    }
# Reaction on SHIP from seller
@adapter.reaction(ship)
async def on_ship(msg):
    global shipments_received, deliveries_attempted, deliveries_successful, deliveries_failed
    # Extract shipment details
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    addr = msg["address"]

    logger.info(f"Received SHIP {shortID} from Seller for {item} destined to {addr}")

    # Determine delivery zone
    z = zones.get(addr, {"zone": "Unknown", "min": 3, "max": 7, "weather": "snow", "risk": "medium"})
    zone_name = z["zone"]
    # Update stats
    shipments_received += 1
    zone_stats[zone_name]["attempts"] += 1
    # Check capacity
    if not has_capacity():
        deliveries_attempted += 1
        reason = "capacity_exceeded"
        logger.info(
            f"Shipment {shortID} to {addr} [{zone_name}] | Decision: DELAY | "
            f"Outcome: {reason} | Reason: No trucks available ({capacity['active_trucks']}/{capacity['max_trucks']})."
        )
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome=reason) # Send DELAY due to capacity
        await adapter.send(d)
        deliveries_failed += 1
        zone_stats[zone_name]["fail"] += 1
        return

    # Reserve truck
    eta_guess = max(1, (z["min"] + z["max"]) // 2)
    asyncio.create_task(occupy_truck(eta_guess))
    # LLM prompt
    prompt = f"""
        You are a winter logistics coordinator. Decide how to handle the shipment below given weather conditions, capacity, and service options:
            Shipment details:
                - ID: {shortID}
                - Item: {item}
                - Address: {addr} ({zone_name} zone)
                - Base ETA: {z['min']}-{z['max']} days
            Operational context:
                - Weather at destination: {z['weather']}
                - Route risk: {z['risk']}
                - Peak Season: {"Yes" if capacity["peak_season"] else "No"}
                - Fleet Capacity: {capacity['active_trucks']} of {capacity['max_trucks']} trucks currently in use
                - Available Trucks: {capacity['max_trucks'] - capacity['active_trucks']}
                - If there are 0 active trucks, that means the full capacity is available for delivery.
                    -Likewise, if there are 6 active trucks, that means no trucks are available for delivery.
                - Service types:
                    - standard: ~{max(z['min'],1)}-{z['max']} days
                    - express: ~max(3, {z['min']}) days
                    - overnight: 1 day (low/medium risk only and capacity permitting)
            Determination:
                - Choose to SHIP, DELAY (weather/capacity), or REJECT (impossible, bad address) the shipment.
                - Pick the best service type available (standard, express, overnight) based on conditions.
                - Provide estimated delivery days (eta_days) within the chosen service and base window.
                - If you cannot safely ship now, set an appropriate outcome like "weather_delay" or "capacity_exceeded".
                - Never set a price. Only worry about making logistical decisions.

        Return your decision in valid JSON format:
        {{
            "decision": "SHIP" | "DELAY" | "REJECT",
            "service": "standard" | "express" | "overnight",
            "eta_days": <int>,
            "outcome": "delivered" | "address_not_found" | "recipient_unavailable" |
                       "damaged_in_transit" | "weather_delay" | "capacity_exceeded",
            "reason": "<brief reasoning>"
        }}
    """
    # Throttle LLM call to avoid rate limits
    await Throttle.wait(30, 40)
    response = await call_llm(prompt, role="shipper")
    # Handle LLM response
    if not response:
        logger.warning(f"LLM failed for {shortID}. Defaulting to SHIP (standard).")
        result = {
            "decision": "SHIP",
            "service": "standard",
            "eta_days": eta_guess,
            "outcome": "delivered",
            "reason": "LLM failure, defaulting to standard shipment.",
        }
    else:
        try:
            cleaned = ( # Parsing LLM response
                response.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
                .replace(",}", "}")
                .replace(",]", "]")
                .replace("“", "\"")
                .replace("”", "\"")
            )
            result = normalize_llm_json(cleaned, z["min"], z["max"])
        except Exception as e:
            logger.warning(f"Invalid JSON for {shortID}. Error: {e}. Using default SHIP.")
            result = {
                "decision": "SHIP",
                "service": "standard",
                "eta_days": eta_guess,
                "outcome": "delivered",
                "reason": "Invalid JSON, defaulting to standard shipment.",
            }

    logger.info(
        f"Shipment {shortID} to {addr} [{zone_name}] | Decision: {result['decision']} | "
        f"Service: {result['service']} | ETA: {result['eta_days']} days | Outcome: {result['outcome']} | "
        f"Reason: {result['reason']}"
    )

    deliveries_attempted += 1
    # If shipper decides not to ship
    if result["decision"] != "SHIP":
        reason = result["outcome"] if result["outcome"] in failure_reasons else "weather_delay"
        logger.info(f"Delivery NOT SHIPPED {shortID}: {item} - {reason}")
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome=reason)
        await adapter.send(d)
        deliveries_failed += 1
        zone_stats[zone_name]["fail"] += 1
        return

    # Delivery success case
    if result["outcome"] == "delivered":
        logger.info(f"Delivery SUCCESS {shortID}: {item} delivered to {addr} in {result['eta_days']} days")
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome="delivered")
        await adapter.send(d)
        deliveries_successful += 1
        zone_stats[zone_name]["success"] += 1
    else:
        reason = result["outcome"] if result["outcome"] in failure_reasons else "weather_delay"
        logger.info(f"Delivery FAILED/DELAYED {shortID}: {item} - {reason}")
        d = make_msg(deliver, ID=ID, item=item, address=addr, outcome=reason)
        await adapter.send(d)
        deliveries_failed += 1
        zone_stats[zone_name]["fail"] += 1
# On buyer DONE
@adapter.reaction("done")
async def on_done(_msg):
    logger.info("Received DONE signal. Printing final shipping stats and stopping...")
    await shipper_stats()
    adapter.stop()
# Final shipping stats
async def shipper_stats():
    logger.info("== FINAL SHIPPING STATUS ===")
    logger.info(f"Shipments received: {shipments_received}")
    logger.info(f"Deliveries attempted: {deliveries_attempted}")
    rate = (deliveries_successful / deliveries_attempted) * 100.0 if deliveries_attempted else 0.0
    logger.info(f"Success rate: {rate:.1f}%")
    logger.info(f"Active trucks: {capacity['active_trucks']}/{capacity['max_trucks']}")
    for zname, zc in zone_stats.items():
        logger.info(f"Zone '{zname}': Attempts: {zc['attempts']}, Success: {zc['success']}, Failures: {zc['fail']}")
# main
async def main():
    logger.info("Awaiting shipping messages...")
    # Keep running until Buyer signals "done"
    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    logger.info("Starting Shipper...")
    adapter.start(main())
