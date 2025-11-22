#!/usr/bin/env bash
set -euo pipefail

# python traditional-packer.py &
python packer.py &
PACKER=$!

python wrapper.py &
WRAPPER=$!

python labeler.py &
LABELER=$!

sleep 2
python merchant.py &
MERCHANT=$!

read -n1 -rsp $'Press any key to stop...\n'

kill $PACKER $WRAPPER $LABELER $MERCHANT



