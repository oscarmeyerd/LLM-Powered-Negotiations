import logging
import random
import uuid
import asyncio

from bspl.adapter import Adapter
from bspl.adapter.core import COLORS
from configuration import systems, agents
from Purchase import rfq, quote, accept, reject, deliver
from bspl.adapter.schema import instantiate

adapter = Adapter("Buyer", systems, agents, color=COLORS[0])
logger = logging.getLogger("buyer")

make_msg = instantiate(adapter) # For instantiation of variables per given bspl/schema.

# Attributes from assignment instructions defined below:
Budget = 1500
Bremaining = Budget

Bitem = {
    "laptop": 950,
    "phone": 800,
    "tablet": 350,
    "watch": 200,
    "headphones": 90
}

# Behavior related
target_items = 3
tolerance = 150
max_requests_per_item = 2
total_RFQs = 5

addresses = ["123 Main St", "456 Oak Ave", "789 Pine Rd"]

# Counters
items_purchased = 0
accepted = 0
rejected = 0
delivered_count = 0
rfqs_sent = 0
quotes_received = 0

# Item specific and tracking
request_count = {it: 0 for it in Bitem}
purchased_per_item = {it: 0 for it in Bitem}
outstanding = {} # RFQ IDs to requested items

# Functions to determine if price is within budget and within tolerance.
def budget_constraint(price: float) -> bool:
    return price <= Bremaining

def item_constraint(item_name: str, price: float) -> bool:
    if price <= Bitem[item_name]:
        return True
    if items_purchased < target_items and (price - Bitem[item_name]) <= tolerance:
        return True
    return False

# Defining reaction to receipt of a quote from the seller.
@adapter.reaction(quote)
async def on_quote(msg):
    global Bremaining, items_purchased, accepted, rejected, quotes_received

    ID = msg["ID"] # ID from schema
    shortID = str(ID)[:8] # Variable to hold 8 byte shortened ID. For logging only - allows matching to sample output in instructions.
    item = msg["item"] # Item from schema
    price = float(msg["price"]) # Price
    quotes_received += 1 # Quote received, add 1 tick

    #Printing to console in format provided.
    logger.info(
        f"Received QUOTE {shortID}: {item} for ${price:.2f} "
        f"(item budget: ${Bitem[item]:.2f}, remaining: ${Bremaining:.2f})"
    )

    # Case if ID is not available (e.g. no RFQ matching ID).
    if ID not in outstanding:
        logger.info(f"Ignoring quote {shortID}: no matching outstanding RFQ")
        return
    
    # Case if target items have been purchased (3). Reject.
    if items_purchased == target_items:
        logger.info(
            f"Rejecting {shortID}: {item} for ${price:.2f} - over item budget and already have {target_items} items"
        )
        rej = make_msg(reject, ID=ID, item=item, price=price, outcome="target_reached", resp=str(uuid.uuid4()))
        await adapter.send(rej)
        rejected += 1
        outstanding.pop(ID, None)
        return

    # Case if >2 of single item purchased already. Reject.
    if purchased_per_item[item] >= max_requests_per_item:
        logger.info(
            f"Rejecting {shortID}: {item} for ${price:.2f} - already purchased {max_requests_per_item} of this item"
        )
        rej = make_msg(reject, ID=ID, item=item, price=price, outcome="per_item_cap", resp=str(uuid.uuid4()))
        await adapter.send(rej)
        rejected += 1
        outstanding.pop(ID, None)
        return

    # Case if buyer is out of money to purchase item. Reject.
    if not budget_constraint(price):
        logger.info(
            f"Rejecting {shortID}: {item} for ${price:.2f} - insufficient total budget (remaining ${Bremaining:.2f})"
        )
        rej = make_msg(reject, ID=ID, item=item, price=price, outcome="insufficient_total_budget", resp=str(uuid.uuid4()))
        await adapter.send(rej)
        rejected += 1
        outstanding.pop(ID, None)
        return

    # Case if buyer has the money or if the buyer has the money and the price is within tolerance.
    if item_constraint(item, price):
        if price > Bitem[item]:
            logger.info(
                f"Accepting {shortID}: {item} for ${price:.2f} - over item budget but <{target_items} items and within ${tolerance} tolerance"
            )
        else:
            logger.info(
                f"Accepting {shortID}: {item} for ${price:.2f}"
            )

        addr = random.choice(addresses) # Address selection at random.
        acc = make_msg(accept, ID=ID, item=item, price=price, address=addr, resp=str(uuid.uuid4()))
        await adapter.send(acc)

         # Updates...

        Bupdate = Bremaining - price # Updating budget for pint statement below.
        logger.info(f"Budget updated: ${Bupdate:.2f} remaining, # items purchased -> {items_purchased + 1}")
        Bremaining = Bupdate

        items_purchased += 1 # Increasing items purchased count.
        purchased_per_item[item] += 1 # Increasing specific item purchased count.
        accepted += 1 # Increasing accepted orders for final stats printout.

    # Final case if the item is over budget due to > tolerance.
    else:
        diff = abs(price - Bitem[item])
        logger.info(
            f"Rejecting {shortID}: {item} for ${price:.2f} - over item budget by ${diff:.2f} (>${tolerance})"
        )
        rej = make_msg(reject, ID=ID, item=item, price=price, outcome="over_item_budget", resp=str(uuid.uuid4()))
        await adapter.send(rej)
        rejected += 1

    outstanding.pop(ID, None)

# Delivery reaction handling delivery notifications from Shipper.
@adapter.reaction(deliver)
async def on_deliver(msg):
    global delivered_count
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    try:
        outcome = msg["outcome"]
    except KeyError:
        outcome = "delivered"
    if outcome == "delivered":
        logger.info(f"Delivery {shortID}: {item} - delivered")
        delivered_count += 1
    else:
        logger.info(f"Delivery {shortID}: {item} - {outcome}")

# RFQ generation.
async def generate_rfqs():
    global rfqs_sent

    items = list(Bitem.keys())
    while rfqs_sent < total_RFQs:
        # Picking item at random based on counter determining if the times requested is < the max requests.
        choices = [it for it in items if request_count[it] < max_requests_per_item]
        if not choices:
            break

        item = random.choice(choices)
        ID = str(uuid.uuid4())
        budget = Bitem[item]

        logger.info(f"Sending RFQ {ID[:8]} for {item} (budget: ${budget:.2f})")

        msg = make_msg(rfq, ID=ID, item=item)
        await adapter.send(msg)

        outstanding[ID] = item
        rfqs_sent += 1
        request_count[item] += 1

        await asyncio.sleep(0.3)

# Final stats printout. 
def buyer_stats():
    spent = Budget - Bremaining
    logger.info("=== FINAL BUYER STATS ==")
    logger.info(f"Budget: Started with ${Budget:.2f}, spent ${spent:.2f}, remaining ${Bremaining:.2f}")
    logger.info(f"Items: purchased {items_purchased}/{target_items} target items")
    logger.info(f"RFQS: {rfqs_sent}, Quotes: {quotes_received}, Accepted: {accepted}, Rejected: {rejected}, Delivered: {delivered_count}")
    logger.info(f"Request counts: {request_count}")
    if items_purchased >= target_items:
        logger.info("SUCCESS: Achieved target of 3 items!")


# Defined main to run upon startup. Starts RFQ generation, sleeps to give time for transactions to take place, then prints final stats.
async def main():
    await generate_rfqs()
    await asyncio.sleep(5)
    buyer_stats()

# Startup sequence from example pys.
if __name__ == "__main__":
    logger.info("Starting Buyer...")
    adapter.start(main())