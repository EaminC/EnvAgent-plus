#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] Starting demo pipeline..."

HOME_DIR="${HOME}"
ENVGYM_DIR="${HOME_DIR}/EnvGym"
TARGET_REPO_DIR="${HOME_DIR}/plonky2-gpu"
ENVBENCH_SCRIPT="${ENVGYM_DIR}/EnvBench/scripts/plonky2-gpu/envbench.sh"

echo "[INFO] Step 1: Checking for git..."
if ! command -v git >/dev/null 2>&1; then
  echo "[INFO] Installing git..."
  sudo apt-get update -y
  sudo apt-get install -y git
else
  echo "[INFO] git already installed"
fi

echo "[INFO] Step 2: Cloning EnvGym..."
if [ -d "${ENVGYM_DIR}/.git" ]; then
  echo "[INFO] EnvGym exists, pulling latest..."
  git -C "${ENVGYM_DIR}" pull --ff-only || echo "[WARN] git pull failed, continuing..."
elif [ -d "${ENVGYM_DIR}" ]; then
  echo "[WARN] ${ENVGYM_DIR} exists but is not a git repo"
else
  git clone https://github.com/EaminC/EnvGym "${ENVGYM_DIR}"
fi

echo "[INFO] Step 3: (Skipped in demo) EnvGym setup already completed"
echo "[INFO] If running fresh, you would run: bash setup.sh"

echo "[INFO] Step 4: Cloning target repo (plonky2-gpu)..."
if [ -d "${TARGET_REPO_DIR}/.git" ]; then
  echo "[INFO] plonky2-gpu exists, pulling latest..."
  git -C "${TARGET_REPO_DIR}" pull --ff-only || echo "[WARN] git pull failed, continuing..."
elif [ -d "${TARGET_REPO_DIR}" ]; then
  echo "[WARN] ${TARGET_REPO_DIR} exists but is not a git repo"
else
  git clone https://github.com/sideprotocol/plonky2-gpu "${TARGET_REPO_DIR}"
fi

echo "[INFO] Step 5: Checking EnvBench script..."
if [ ! -f "${ENVBENCH_SCRIPT}" ]; then
  echo "[ERROR] EnvBench script not found at ${ENVBENCH_SCRIPT}"
  exit 1
fi

echo "[INFO] Step 6: Running EnvBench test..."
cd "$(dirname "${ENVBENCH_SCRIPT}")"
chmod +x envbench.sh
bash envbench.sh

echo "[INFO] Step 7: Demo completed successfully!"

echo "[INFO] Output files:"
echo "  - ${TARGET_REPO_DIR}/envgym/envbench.json"
echo "  - ${TARGET_REPO_DIR}/envgym/report.txt"
echo "  - ${TARGET_REPO_DIR}/envgym/hardware.txt"