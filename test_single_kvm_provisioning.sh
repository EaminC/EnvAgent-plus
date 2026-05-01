#!/bin/bash
# Single repo KVM provisioning validation test
# Shows all hardware matching output clearly

set -e

echo "=========================================="
echo "Single Repo KVM Provisioning Validation"
echo "=========================================="
echo ""

# Get first test repo
REPO=$(head -1 /home/cc/EnvAgent-plus/repos_test.txt | xargs)
if [ -z "$REPO" ]; then
    echo "ERROR: No repos found in repos_test.txt"
    exit 1
fi

echo "Testing repo: $REPO"
echo ""

# Set up environment
cd /home/cc/EnvAgent-plus
source /tmp/kvm_test_openrc.sh 2>/dev/null
source venv/bin/activate

# Run single provisioning with verbose output
echo "Starting provisioning..."
echo ""

python 2.0/src/provision_v2.py \
    --repo "$REPO" \
    --site "KVM@TACC" \
    --lease-duration 2 \
    2>&1 | tee /tmp/kvm_test_single.log

echo ""
echo "=========================================="
echo "Provisioning Complete"
echo "=========================================="

# Extract hardware validation from log
echo ""
echo "Hardware Validation Extracted:"
grep -A 20 "HARDWARE VALIDATION SUMMARY" /tmp/kvm_test_single.log || echo "  (not found in logs)"

# Look for saved JSON with hardware info
LATEST_JSON=$(ls -t auto-server-*_info.json 2>/dev/null | head -1)
if [ -n "$LATEST_JSON" ]; then
    echo ""
    echo "JSON Output: $LATEST_JSON"
    echo ""
    python3 -m json.tool "$LATEST_JSON" | head -40
fi

echo ""
echo "Full log saved to: /tmp/kvm_test_single.log"
