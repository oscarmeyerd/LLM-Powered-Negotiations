"""
Seller agent for Purchase protocol.
Receives RFQs, sends quotes, processes accepts/rejects, and ships items.
"""
import logging
import asyncio
import json
import random

from bspl.adapter import Adapter
from bspl.adapter.core import COLORS
from configuration import systems, agents
from Purchase import rfq, quote, accept, reject, ship
from bspl.adapter.schema import instantiate
from llm import call_llm
from throttle import Throttle

adapter = Adapter("Seller", systems, agents, color=COLORS[1])
logger = logging.getLogger("seller")
stock_lock = asyncio.Lock()

make_msg = instantiate(adapter)

# Assignment variables
base_prices = {
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
# initial stock levels
stock = {
    "ski_boots": 5,
    "skis": 5,
    "ski_poles": 8,
    "winter_jacket": 20,
    "ski_goggles": 10,
    "gloves": 12,
    "thermal_underwear": 15,
    "hydration_pack": 10,
    "ski_socks": 25
}
# parameters
cost_factor = 0.6
profit_margin = 0.4
high_price = 2000

# Counters
quotes_sent = 0
orders_accepted = 0
orders_rejected = 0
orders_shipped = 0
last_quotes = {}
# Baseline price calc
def baseline_price(item):
    """Compute standard retail markup before LLM."""
    cost = base_prices[item] * cost_factor
    target = cost * (1 + profit_margin)
    return round(target, 2)
# Reaction on RFQ
@adapter.reaction(rfq)
async def on_rfq(msg):
    global quotes_sent
    # Extracting information from buyer message
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    # Case of unknown item
    if item not in base_prices:
        logger.warning(f"RFQ {shortID}: unknown item '{item}', rejecting.")
        r = make_msg(reject, ID=ID, item=item, price=high_price, outcome="unknown item", resp="N/A")
        await adapter.send(r)
        await asyncio.sleep(random.uniform(6.0, 10.0))
        return
    
    stock_level = stock.get(item, 0)
    base = baseline_price(item)
    #LLM prompt
    prompt = f"""
        You are a seller of ski equipment currently operating at the season's peak demand. You must determine the optimal
        quote price for {item} based on the following context:

        - Seasonal demand is high due to this being the peak part of the ski season.
        - Inventory status: {stock_level} units of {item} remaining.
        - Competition: This is a competitive market, so pricing must be attractive yet profitable.
        - Cost structure: you acquire the goods at 60% of the retail price and aim for a 40% profit margin.
        - Current retail baseline price for {item} is {base_prices[item]:.2f}.
        - Cost basis: ${base_prices[item] * cost_factor:.2f}.
        - Baseline profit price: ${base:.2f}.

        - Price items reasonably based on stock and demand:
            - Essential items: ski_boots, skis, ski_poles -> higher demand, lower stock, can command premium (higher) pricing.
                - Never price essential items below the baseline unless the stock for those items is very high.
            - Non-essential items: winter_jacket, ski_goggles, gloves -> moderate demand, higher stock, competitive pricing.
            - Optional items: thermal_underwear, hydration_pack, ski_socks -> lower demand, ample stock, budget-friendly pricing.

        Remember to:
        1. Offer competitive yet profitable prices.
        2. Price aggressively vs competitors while maintaining profitability.
        3. Consider stock levels in pricing strategy.
        4. Avoid pricing below cost basis (60% of retail).
        5. Return reasoning that shows understanding of market dynamics.

        Return your decision in valid JSON format:
        {{
            "decision": "QUOTE" | "DECLINE",
            "price": <float>,
            "reason": "Short explanation of pricing decision considering stock, demand, competition, and profitability."
        }}
    """
    # Throttle LLM call to avoid rate limits
    await Throttle.wait(5, 10)
    response = await call_llm(prompt, role="seller")
    # Handle LLM response
    if not response:
        logger.warning(f"LLM failed to create quote for RFQ {shortID}. Quoting at base price ${base:.2f}.")
        result = {"decision": "QUOTE", "price": base, "reason": "LLM failure, defaulting to base price."}
    else:
        try:
            cleaned = ( #Parsing LLM response
                response.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
            cleaned = cleaned.replace(",}", "}").replace(",]", "]")
            cleaned = cleaned.replace("“", "\"").replace("”", "\"")
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON for RFQ {shortID}. Quoting at base price ${base:.2f}.")
            result = {"decision": "QUOTE", "price": base, "reason": "Invalid JSON, defaulting to base price."}
    # Extract decision and price
    decision = result.get("decision", "QUOTE").upper()
    price = float(result.get("price", base))
    # Making sure price is above cost
    min_price = base_prices[item] * cost_factor
    if price < min_price:
        price = min_price
        logger.warning(f"Raised quote {shortID} for {item} to minimum ${min_price:.2f} (avoid below cost).")
    # If seller decides to quote
    if decision == "QUOTE":
        logger.info(f"RFQ {shortID}: quoting {item} at ${price:.2f} - {result.get('reason', '')} (Stock: {stock_level})")
        q = make_msg(quote, ID=ID, item=item, price=price)
        await adapter.send(q)
        quotes_sent += 1
        last_quotes[ID] = {"item": item, "price": price}
    else: #Quote declined
        logger.info(f"RFQ {shortID}: declining {item} - {result.get('reason', '')}")
        r = make_msg(reject, ID=ID, item=item, price=high_price, outcome="declined to quote", resp="N/A")
        await adapter.send(r)

    await asyncio.sleep(random.uniform(6.0, 10.0))
# Reaction on ACCEPT from buyer
@adapter.reaction(accept)
async def on_accept(msg):
    global orders_accepted, orders_rejected, orders_shipped
    # Extracting information from buyer message
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]
    price = float(msg["price"])

    try:
        addr = msg["address"] 
    except KeyError:
        addr = "N/A"
    # Lock included to prevent race conditions
    async with stock_lock:
        # Reject order if item is out of stock
        if stock.get(item, 0) <= 0:
            logger.info(f"Reject {shortID}: {item} - reason: out of stock")
            r = make_msg(reject, ID=ID, item=item, price=price, outcome="out of stock", resp="NA")
            await adapter.send(r)
            orders_rejected += 1
            return

        # Decrement stock and increment orders accepted
        stock[item] -= 1
        orders_accepted += 1

        logger.info(f"Accept {shortID}: {item} for ${price:.2f} to {addr} (remaining stock: {stock[item]})")
        logger.info(f"Initiating shipping for {shortID}")

        s = make_msg(ship, ID=ID, item=item, address=addr, shipped=True)
        await adapter.send(s)
        orders_shipped += 1
        logger.info(f"Sent SHIP message for {item} ({shortID}) to {addr}")

        # no negative stock
        if stock[item] < 0:
            stock[item] = 0
# ON a buyer REJECT
@adapter.reaction(reject)
async def on_reject(msg):
    global orders_rejected
    ID = msg["ID"]
    shortID = str(ID)[:8]
    item = msg["item"]

    # Extract reason for rejection
    try:
        reason = msg["outcome"]
    except KeyError:
        reason = msg.bindings.get("outcome", "unknown") if hasattr(msg, "bindings") else "unknown"

    logger.info(f"Reject {shortID}: {item} - reason: {reason}")
    orders_rejected += 1
# Buyer DONE reaction
@adapter.reaction("done")
async def on_done(_msg):
    logger.info("Received DONE signal. Printing final stats and stopping...")
    await seller_stats()
    adapter.stop()
# Final stats
async def seller_stats():
    logger.info("=== FINAL INVENTORY STATUS ===")
    for it in base_prices:
        logger.info(f"{it}: {stock[it]} units remaining  @ ${base_prices[it]:.2f}")
    logger.info("=== FINAL SELLER STATS ===")
    logger.info(f"Stats - Quotes: {quotes_sent}, Accepted: {orders_accepted}, Rejected: {orders_rejected}, Shipped: {orders_shipped}")

async def main():
    logger.info("Awaiting messages...")
    # Loop keeps agent alive until adapter.stop() is called
    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    logger.info("Starting Seller...")
    adapter.start(main())