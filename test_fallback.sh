#!/bin/bash
# Test script for fallback strategy

set -euo pipefail

cd /home/cc/EnvAgent-plus

# Create test log directory
mkdir -p logs_test

# Activate venv and credentials
source venv/bin/activate
source config/CHI-251467-openrc-2.sh

# Test repo
TEST_REPO="https://github.com/rayon-rs/rayon"
LOG_FILE="logs_test/$(date +%Y%m%d_%H%M%S)_rayon_test.log"

echo "Testing fallback strategy with: $TEST_REPO"
echo "Logging to: $LOG_FILE"
echo ""

# Run the provisioning
python 2.0/src/provision_v2.py --repo "$TEST_REPO" --site tacc 2>&1 | tee "$LOG_FILE"

echo ""
echo "Test complete! Log saved to: $LOG_FILE"
