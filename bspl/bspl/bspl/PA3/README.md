About:

This system contains three LLM-powered agents (Buyer, seller, shipper) which participate in a purchase protocol, interacting freely between each other to make decisions based on communications from one another in addition to several constraints that influence how those decisions are made.

The purchase protocol followed in this system is available in "purchase.bspl" or below for ease:

Purchase {
    roles Buyer, Seller, Shipper
    parameters out ID key, out item, out price, out outcome
    private address, resp, shipped

    Buyer -> Seller: rfq[out ID, out item,]
    Seller -> Buyer: quote[in ID, in item, out price]

    Buyer -> Seller: accept[in ID, in item, in price, out address, out resp]
    Buyer -> Seller: reject[in ID, in item, in price, out outcome, out resp]

    Seller -> Shipper: ship[in ID, in item, in address, out shipped]
    Shipper -> Buyer: deliver[in ID, in item, in address, out outcome]
}

Plainly, this purchase protocol demonstrates how the system fulfills all communications. First, the buyer will generate requests for quotes with a unique ID for a random item selected from a predetermined list. The seller will respond with a quote containing that same unique ID and item while providing a price offer for the buyer. The buyer will then accept or reject based on several defined constraints. In the accept case, the buyer provides a shipping address to the seller, who then forwards all information to the shipper for delivery. On rejection, the communications iterate to the next quote.

Each agent has an integrated LLM model to power its decision making. Each agent was provided a prompt to include factors that the LLM should consider when making decisions. Those possible decisions and factors/constraints are listed below. For additional context, these agents are fulfilling transactions given a specific scenario. That scenario is also described below:

Scenario:

This three-agent system revolves around a 4-person family ski trip in which the buyer (coordinator) must purchase essential items (ski boots, skis, and ski poles), while having the option to purchase several other items and varying priority levels. The family departs in three weeks, making early receipt of the highest priority items important. There are three delivery address options, and three delivery service options. Each agent must carefully weigh several criteria in their decision making processes to ensure each transaction takes place efficiently with purpose. Those criteria are below:

Buyer:
    Starting budget of $6000
    Specific budgets for each item
    Target to purchase each essential item for each member of the family
    Stop requesting items after purchasing essential items, or when out of money to purchase an essential item.
    
    Necessary considerations:
    Weather impacts
    Item priorities
    When to stop requesting quotes
    What address to choose based on urgency and logistics

    The buyer can either accept or reject a quote or choose to stop sending RFQs.

Seller:
    Peak ski season pricing
    Inventory levels
    Competition with other members of the market
    Profit (Items cost 60% of retail value, target 40% profit)

    The seller should take the above into account when creating a quote for the buyer. Item prices must be competitive, while ensuring the profit mark is being met. Once a quote is accepted, the seller should forward shipping information to the shipper. If a quote is rejected, the seller should process the rejection. Once the buyer issues a stop message, the seller should print the resulting stock levels, quotes accepted, and quotes rejected.

Shipper:
    Shipping zones (to determine shipping time and success rate of delivery)
    Weather constraints
    Operational constraints (capacity)
    Service considerations and delivery timelines
    Outcome of each delivery attempt

    The shipper will receive shipping information from the seller which determines shipping zones and success rates. Shipping delays (or failures) are determined by weather conditions at the delivery address and vehicle capacity. The shipper should evaluate the safety and efficiency of its operations to determine appropriate delivery methods, then deliver a shipping message to the buyer.

Again, each agent will carefully consider all of the above constraints and context to determine the best course of action given a single transaction. The agents will each provide careful reasoning behind their decision making.


System setup instructions:

1. Verify Python v. 3.12.2 is installed on your host (python --version)
2. Unzip PA3.zip
3. Locate ".env"
    a. Locate the three lines starting with "OPENROUTER_API_KEY="
    b. Navigate to https://openrouter.ai/settings/keys
    c. Generate three new API keys named for each agent.
        i. Do not close the key generation window before copying each key. You will not be able to see them again.
    d. Enter each key into the appropriate line located in step 3.a.
    e. Save the file.

4. From .\PA3\ run:
    $ pip install -e .
    $ pip install aiohttp
    $ pip install python-dotenv
    
5. Run the startup script:
    Windows (PowerShell)
    $ .\start.ps1

    Linux/MacOS
    $ ./start.sh

Three windows should populate with the communications described above.

Author: Dom Bulone
Date: 8 NOV 2025