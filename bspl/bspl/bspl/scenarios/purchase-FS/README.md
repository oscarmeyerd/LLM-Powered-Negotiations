About:

This system contains three agents (Buyer, seller, shipper) which participate in a purchase protocol, interacting freely between each other to make decision based on communications from one another in addition to several constraints that influence how those decisions are made.

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

Constraints and requirements:

Buyer:
    Starting budget of $1500
    Specific budgets for each item
    Target to purchase three items
    Tolerance of $150
    Can maximally request quotes for a single item twice
    Can maximally request five quotes
    Three shipping addresses to randomlly choose from

    The buyer will only accept a quote if it is within its budget and/or tolerance, if it has purchased less than two of that item, or if it has purchased less than three total items.

Seller:
    Base prices (lowest price the agent will sell a specific item for)
    Initial stock
    Maximum stock
    Demand scaling (stock based)
    Market variation
    High price

    The seller maintains an inventory with unique prices based on demand, market variation, and the item's base price. The seller will send quotes to the buyer that are dynamically priced based on those factors. Low stock drives prices up to show the supply/demand relationship. 

Shipper:
    Shipping zones (to determine shipping time and success rate of delivery)
    Delivery failure reasons
    Processing delays
    Delivery delays

    The shipper will receive shipping information from the seller which determines shipping zones and success rates. Processing delays are determined randomly whereas shipping delays are calculated by a zone's delivery days and a 0.2 time compression. Delivery will succeed if a randomly selected number is less than the specific success rate of a zone. Delivery reporting is made to the buyer regardless of success.


System setup instructions:

1. Verify Python v. 3.12.2 is installed on your host (python --version)
2. Unzip purchase-FS.zip
3. From ./purchase-FS/ or .\purchase-FS\ (Windows)
    $ Install BSPL: pip install -e .
4. Run the startup script:
    Linux / macOS:
    $ ./start.sh
    Windows (PowerShell)
    $ ./start.ps1

Three windows should populate with the communications described above.

Author: Dom Bulone
Date: 11 OCT 2025