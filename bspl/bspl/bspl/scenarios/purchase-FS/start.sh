#!/usr/bin/env bash
set -euo pipefail

echo "Starting Enhanced Purchase Scenario (purchase-FS)"
echo "This demonstrates a complete purchase workflow with Buyer, Seller, and Shipper agents"

# Start service providers in background
echo "Starting Seller..."
python seller.py &
SELLER=$!

echo "Starting Shipper..."
python shipper.py &
SHIPPER=$!

# Wait for services to initialize
sleep 2

echo "Starting Buyer..."
python buyer.py &
BUYER=$!

echo ""
echo "=== Purchase Scenario Started ==="
echo "Watch the interaction between the three agents:"
echo "  - Seller: Processes RFQs and manages inventory"
echo "  - Shipper: Handles logistics and deliveries"  
echo "  - Buyer: Initiates purchases and makes decisions"
echo ""
echo "The buyer will send 5 purchase requests and make decisions based on pricing."
echo ""

read -n1 -rsp $'Press any key to stop...\n'

echo "Stopping all agents..."
kill $SELLER $SHIPPER $BUYER
echo "All agents stopped."