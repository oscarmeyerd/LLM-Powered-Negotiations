"""
This agent handles RFQs by generating quotes and processing accept/reject responses.
It manages inventory and pricing, and coordinates with shippers for accepted orders.
"""

"""
Seller agent for Purchase protocol.
Receives RFQs, sends quotes, processes accepts/rejects, and ships items.
"""
import logging
import random
import asyncio
from bspl.adapter import Adapter
from configuration import systems, agents
from Purchase import rfq, quote, accept, reject, ship
from bspl.adapter.schema import instantiate

adapter = Adapter("Seller", systems, agents)
logger = logging.getLogger("seller")

make_msg = instantiate(adapter) # For instantiation of variables per given bspl/schema.

# Assignment dictated variables below.
base_price = {
    "laptop": 1000,
    "phone": 800,
    "tablet": 500,
    "watch": 300,
    "headphones": 100,
}
stock = {
    "laptop": 10,
    "phone": 15,
    "tablet": 8,
    "watch": 20,
    "headphones": 25,
}

max_stock = 25
demand_scaling = 0.02
min_variation, max_variation = 0.8, 1.2
high_price = 2000

# Counters
quotes_sent = 0
orders_accepted = 0
orders_rejected = 0
orders_shipped = 0

last_quotes = {} # Sent quotes for validation upon acceptance.

# Pricing item based on stock and variation.
def dynamic_price(item_name: str) -> float:
    if stock.get(item_name, 0) <= 0:
        return high_price
    demand_factor = 1.0 + (max_stock - stock[item_name]) * demand_scaling
    market_variation = random.uniform(min_variation, max_variation)
    return round(base_price[item_name] * demand_factor * market_variation, 2)

# Reaction upon RFQ from buyer.
@adapter.reaction(rfq)
async def on_rfq(msg):
    global quotes_sent

    ID = msg["ID"] # Extracting ID and item, storing int ID and item.
    shortID = str(ID)[:8] # For logging neatly.
    item = msg["item"]

    # If the item doesn't exist, quote @ the high price, else refer to above dynamic_price function.
    if item not in base_price:
        price = float(high_price)
    else:
        price = dynamic_price(item)

    logger.info(f"RFQ {shortID}: quoting {item} at ${price:.2f} (Stock: {stock.get(item,0)})")
    # Quote message creation and sending to buyer.
    q = make_msg(quote, ID=ID, item=item, price=price)
    await adapter.send(q)
    # Increment quotes sent.
    quotes_sent += 1
    # Storing values for validation.
    last_quotes[ID] = {"item": item, "price": price}

# Reaction upon buyer accept.
@adapter.reaction(accept)
async def on_accept(msg):
    global orders_accepted, orders_rejected, orders_shipped
    # Extracting information from buyer message
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    price = float(msg["price"])
    # Extracting address from buyer message
    try:
        addr = msg["address"] # Using try/except after issues running code similarly to other schema (e.g. addr = get.msg["address", "unknown"])
    except KeyError:
        addr = "N/A"
    # Rejects order if item is out of stock.
    if stock.get(item, 0) <= 0:
        logger.info(f"Reject {shortID}: {item} - reason: out of stock")
        r = make_msg(reject, ID=ID, item=item, price=price, outcome="out of stock", resp="NA")
        await adapter.send(r)
        orders_rejected += 1
        return
    # Decrement stock for specific item and increment orders accepted.
    stock[item] -= 1
    orders_accepted += 1

    logger.info(f"Accept {shortID}: {item} for ${price:.2f} to {addr} (remaining stock: {stock[item]})")
    logger.info(f"Initiating shipping for {shortID}")
    # Creation of message to shipper to begin delivery. Sends.
    s = make_msg(ship, ID=ID, item=item, address=addr, shipped=True)
    await adapter.send(s)
    orders_shipped += 1

# Reaction upon buyer rejection.
@adapter.reaction(reject)
async def on_reject(msg):
    global orders_rejected
    # Extracting and storing schema.
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    # Rejection logging with outcome.
    try:
        reason = msg["outcome"] # Using try/except after issues running code similarly to other schema.
    except KeyError:
        reason = "unknown"
    logger.info(f"Reject {shortID}: {item} - reason: {reason}")
    orders_rejected += 1
# Final statistics for printing.
async def seller_stats():
    logger.info("=== FINAL INVENTORY STATUS ===")
    for it in base_price:
        logger.info(f"{it}: {stock[it]} units @ ${base_price[it]:.2f} base")
    logger.info("=== FINAL SELLER STATS ===")
    logger.info(f"Stats - Quotes: {quotes_sent}, Accepted: {orders_accepted}, Rejected: {orders_rejected}, Shipped: {orders_shipped}")

# Same as buyer.py syntax.
async def main():
    await asyncio.sleep(5)
    await seller_stats()

if __name__ == "__main__":
    logger.info("Starting Seller...")
    adapter.start(main())