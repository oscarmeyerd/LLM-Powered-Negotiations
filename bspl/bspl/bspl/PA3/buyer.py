import logging
import random
import uuid
import asyncio
import json

from bspl.adapter import Adapter
from bspl.adapter.core import COLORS
from configuration import systems, agents
from Purchase import rfq, quote, accept, reject, deliver
from bspl.adapter.schema import instantiate
from throttle import Throttle
from llm import call_llm

adapter = Adapter("Buyer", systems, agents, color=COLORS[0])
logger = logging.getLogger("buyer")

make_msg = instantiate(adapter)  # For instantiation of variables per given bspl/schema.

# Assignment attributes
Budget = 6000 #Changed from assignment determinet 1800 due to all 4 members not being able to get essential items with that budget.
Bremaining = Budget
# Per item budgets for seller
Bitem = {
    "ski_boots": 400,
    "skis": 600,
    "ski_poles": 150,
    "winter_jacket": 350,
    "ski_goggles": 200,
    "gloves": 100,
    "thermal_underwear": 80,
    "hydration_pack": 120,
    "ski_socks": 40
}

# Tracker to be used on stop messaging. Need to ensure LLM purchases 12 required items prior to sending done message.
essential_items = {"ski_boots", "skis", "ski_poles"}
group_size = 4
required_essentials = len(essential_items) * group_size

# Track how many of each essential were delivered to the buyer.
essentials_delivered = {item: 0 for item in essential_items}
essentials_failed = {item: 0 for item in essential_items}

# Keep this consistent with Shipper zones!
address_list = ["789 Pine Rd", "456 Oak Ave", "123 Main St"]

# Counters
items_purchased = 0
accepted = 0
rejected = 0
delivered_count = 0
failed_count = 0
rfqs_sent = 0
quotes_received = 0

outstanding = {}
shopping_done = False  # signals completion

@adapter.reaction(quote)
async def on_quote(msg):
    global Bremaining, items_purchased, accepted, rejected, quotes_received, shopping_done #global variables
    # message fields extraction
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    price = float(msg["price"])
    quotes_received += 1

    logger.info(
        f"Received QUOTE {shortID}: {item} for ${price:.2f} "
        f"(item budget: ${Bitem.get(item, 0):.2f}, remaining: ${Bremaining:.2f})"
    )
    # Case for unknown item
    if item not in Bitem:
        logger.warning(f"Received quote for unknown item '{item}' — ignoring.")
        return
    # Case for a quote that exceeds remaining budget
    if price > Bremaining:
        logger.info(f"Skipping QUOTE {shortID}: {item} - exceeds remaining budget ${Bremaining:.2f}")
        return

    # Decision prompt to the LLM
    prompt = f"""
    You are a buyer planning to purchase ski gear for 4 people attending a 5-day ski trip in 3 weeks. Heavy snow is expected, so essential
    items must be delivered before the trip. Keep in mind, the whole family of four needs one of each essential item. 
    Non-essential items are optional. Here is the context:

    - Item: {item}
    - Offered price: ${price:.2f}
    - Item budget: ${Bitem[item]:.2f}
    - Remaining total budget: ${Bremaining:.2f}
    - Essential items (NEED one of each for all four people): ski_boots ($400), skis ($600), ski_poles ($150)
    - Important (NOT ESSENTIAL): winter_jacket, ski_goggles, gloves
    - Optional: thermal_underwear, hydration_pack, ski_socks
    - Addresses (priority order): 789 Pine Rd (long delivery time/blizzard), 456 Oak Ave (moderate delivery time/snowing), 123 Main St (low delivery time/clear)
    - Decide on an address based on weather conditions, length of simulation run time, and urgency of receiving item.
    - Weather conditions may lead to delivery delays. Be smart about choosing a delivery address.

    Rules:
    1. Always accept essential items if price ≤ 120% of their budget.
    2. Reject non-essential items (important, optional) unless well under budget or remaining funds are high.
    3. Stop buying if all essential items are acquired or remaining funds < $1000.
    4. Do not stop shopping unless all essential items are secured for all 4 people, or if the budget is critically low (< lowest item cost).

    Return ONLY JSON:
    {{
      "decision": "ACCEPT" | "REJECT" | "STOP",
      "reason": "Brief reasoning",
      "address": "789 Pine Rd" | "456 Oak Ave" | "123 Main St"
    }}
    """
    # Throttle incall to avoid rate limits
    await Throttle.wait(30, 40)
    response = await call_llm(prompt, role="buyer")
    # Case when LLM fails to respond
    if not response:
        result = {"decision": "REJECT", "reason": "LLM failed to respond."}
    else:
        try: #Parsing LLM response
            cleaned = (
                response.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
                .replace(",}", "}")
                .replace("“", "\"")
                .replace("”", "\"")
            )
            result = json.loads(cleaned)
        except Exception: # Case for invalid JSON
            logger.warning("Invalid JSON from LLM. Rejecting by default.")
            result = {"decision": "REJECT", "reason": "Invalid JSON"}

    decision = result.get("decision", "REJECT").upper()
    # Case for accepting a quote
    if decision == "ACCEPT":
        addr = result.get("address") #Getting address from LLM response
        if addr not in address_list:
            addr = "123 Main St"
        logger.info(f"Accepting QUOTE {shortID} for {item} at ${price:.2f}, delivery to {addr} - {result.get('reason', '')}") 
        acc = make_msg(accept, ID=ID, item=item, price=price, address=addr, resp=str(uuid.uuid4())) # Creating ACCEPT message
        await adapter.send(acc)
        await asyncio.sleep(0.5)
        # Update budget and counters
        Bremaining -= price
        items_purchased += 1
        accepted += 1
        # Check stopping conditions
        if Bremaining < 1000 or items_purchased >= len(["ski_boots", "skis", "ski_poles"]) * 4:
            await stop_shopping(reason="Essential items secured or budget low.")
            return
    # Case for stopping shopping
    elif decision == "STOP":
        reason = result.get("reason", "LLM decided to stop.")
        await stop_shopping(reason=reason)
        return
    # Providing reason for rejecting a quote
    else:
        reason_text = result.get("reason") or "Buyer rejected quote per evaluation"
        rej = make_msg(
            reject,
            ID=ID,
            item=item,
            price=price,
            outcome=reason_text,
            resp=str(uuid.uuid4())
        )
        await adapter.send(rej)

        logger.info(f"Rejected QUOTE {shortID}: {item} - Reason sent to seller: {reason_text}")
        rejected += 1
# Delivery reaction
@adapter.reaction(deliver)
async def on_deliver(msg):
    global delivered_count, failed_count
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]

    try:
        outcome = msg["outcome"]
    except KeyError:
        outcome = "delivered"

    if outcome == "delivered":
        logger.info(f"Delivery {shortID}: {item} delivered successfully.")
        delivered_count += 1
        if item in essentials_delivered:
            essentials_delivered[item] += 1
    else:
        logger.info(f"Delivery {shortID}: {item} failed - {outcome}")
        failed_count += 1
        if item in essentials_failed:
            essentials_failed[item] += 1

    ##Ensuring all essential items have been delivered for all 4 members before stopping shopping.
    essential_done = all(
        essentials_delivered[i] + essentials_failed[i] >= group_size
        for i in essential_items
    )
    # Stop shopping if all essential items have been delivered or failed for all 4 members.
    if essential_done:
        await stop_shopping(reason="All essential items delivered or failed for all 4 members.")
# Stop shopping procedure
async def stop_shopping(reason: str):
    global shopping_done
    if shopping_done:
        return
    shopping_done = True
    logger.info(f"LLM stopping transactions. Reason: {reason}")

    # Send DONE to all agents
    done_msg = make_msg("done", role="Buyer", reason=reason)
    await adapter.send(done_msg)

    buyer_stats()
    logger.info("Sent DONE message to all participants.")
    adapter.stop()
# Done reaction - sends to other agents
@adapter.reaction("done")
async def on_done(_msg):
    logger.info("Received DONE signal. Printing final stats and stopping...")
    buyer_stats()
    adapter.stop()
# RFQ generation
async def generate_rfqs():
    global rfqs_sent
    for item in list(Bitem.keys()):
        ID = str(uuid.uuid4())
        logger.info(f"Sending RFQ {ID[:8]} for {item}")
        msg = make_msg(rfq, ID=ID, item=item)
        await adapter.send(msg)
        rfqs_sent += 1
        outstanding[ID] = item
        await asyncio.sleep(random.uniform(2, 4))
# Final stats
def buyer_stats():
    spent = Budget - Bremaining
    logger.info("=== FINAL BUYER STATS ===")
    logger.info(f"Budget: Started with ${Budget:.2f}, spent ${spent:.2f}, remaining ${Bremaining:.2f}")
    logger.info(f"RFQs: {rfqs_sent}, Quotes: {quotes_received}, Accepted: {accepted}, Rejected: {rejected}, Delivered: {delivered_count}")
# Main
async def main():
    await asyncio.sleep(10)
    await generate_rfqs()
    while not shopping_done:
        await asyncio.sleep(10)

if __name__ == "__main__":
    logger.info("Starting Buyer...")
    adapter.start(main())