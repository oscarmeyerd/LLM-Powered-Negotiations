"""
This scenario demonstrates implementing BSPL agents using Python decorators for a purchase protocol.
The Purchase protocol involves three agents: Buyer, Seller, and Shipper working together to complete purchases.
Based on the logistics scenario structure but adapted for purchase workflow.
"""

import bspl

purchase = bspl.load_file("purchase.bspl").export("Purchase")
from Purchase import Buyer, Seller, Shipper

agents = {
    "Buyer": [("127.0.0.1", 8000)],
    "Seller": [("127.0.0.1", 8001)],
    "Shipper": [("127.0.0.1", 8002)],
}

systems = {
    "purchase": {
        "protocol": purchase,
        "roles": {
            Buyer: "Buyer",
            Seller: "Seller",
            Shipper: "Shipper",
        },
    },
}