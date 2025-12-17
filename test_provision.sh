#!/bin/bash

################################################################################
# EnvAgent-plus Provisioning Test Runner
# 
# Purpose: Test end-to-end provisioning behavior on real GitHub repositories
# 
# Usage:
#   ./test_provision.sh [--repo REPO_URL] [--duration HOURS] [--site SITE]
# 
# Example:
#   ./test_provision.sh --repo https://github.com/pytorch/examples --duration 1 --site uc
#
# What this does:
#   1. Validates prerequisites (venv, credentials)
#   2. Captures stdout/stderr to both console and log file
#   3. Logs key milestones (repo clone, image selection, etc.)
#   4. Provides structured pass/fail reporting
#   5. Easy to extend to multiple repos later
################################################################################

set -o pipefail  # Propagate errors from piped commands

# Default values
REPO_URL="https://github.com/pytorch/examples"
LEASE_DURATION=""  # Empty by default - AI will decide
SITE="uc"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="./test_logs"
LOG_FILE="${LOG_DIR}/provision_${TIMESTAMP}.log"
SUMMARY_FILE="${LOG_DIR}/provision_${TIMESTAMP}_summary.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --duration)
      LEASE_DURATION="$2"
      shift 2
      ;;
    --site)
      SITE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

################################################################################
# Helper functions
################################################################################

log_info() {
  echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
  echo -e "${GREEN}[✓]${NC} $*"
}

log_error() {
  echo -e "${RED}[✗]${NC} $*"
}

log_warning() {
  echo -e "${YELLOW}[⚠]${NC} $*"
}

# Log to both console and file
log_both() {
  local msg="$1"
  echo "$msg" | tee -a "$LOG_FILE"
}

################################################################################
# Pre-flight checks
################################################################################

run_preflight_checks() {
  log_info "Running pre-flight checks..."
  
  # Check if venv is activated
  if [[ -z "$VIRTUAL_ENV" ]]; then
    log_error "Virtual environment not activated. Please run:"
    echo "  source venv/bin/activate"
    return 1
  fi
  log_success "Virtual environment is active"
  
  # Check if Chameleon credentials are set
  if [[ -z "$OS_AUTH_URL" ]]; then
    log_error "Chameleon credentials not loaded. Please run:"
    echo "  source ./config/CHI-251467-openrc.sh"
    return 1
  fi
  log_success "Chameleon credentials loaded"
  
  # Check if provision script exists
  if [[ ! -f "2.0/src/provision_v2.py" ]]; then
    log_error "Provision script not found: 2.0/src/provision_v2.py"
    return 1
  fi
  log_success "Provision script found"
  
  # Check if .env exists
  if [[ ! -f "2.0/src/.env" ]]; then
    log_warning ".env file not found in 2.0/src/"
    log_warning "AI functionality may not work"
  else
    log_success ".env configuration found"
  fi
  
  return 0
}

################################################################################
# Main test execution
################################################################################

run_test() {
  log_both ""
  log_both "================================================================================"
  log_both "EnvAgent-plus Provisioning Test"
  log_both "================================================================================"
  log_both "Timestamp:      $(date)"
  log_both "Repository:     $REPO_URL"
  log_both "Lease Duration: $LEASE_DURATION hour(s)"
  log_both "Site:           $SITE"
  log_both "Log File:       $LOG_FILE"
  log_both "================================================================================"
  log_both ""
  
  # Build the provisioning command
  local cmd="python 2.0/src/provision_v2.py"
  cmd="$cmd --repo $REPO_URL"
  
  # Only add lease duration if specified
  if [[ -n "$LEASE_DURATION" ]]; then
    cmd="$cmd --lease-duration $LEASE_DURATION"
    log_both "Lease Duration: $LEASE_DURATION hour(s)"
  else
    log_both "Lease Duration: AI will decide"
  fi
  
  cmd="$cmd --site $SITE"
  
  log_both "Command: $cmd"
  log_both ""
  
  # Run the provisioning with output capture
  log_info "Starting provisioning process..."
  
  # Capture exit code while preserving output
  if $cmd 2>&1 | tee -a "$LOG_FILE"; then
    local exit_code=0
  else
    local exit_code=$?
  fi
  
  log_both ""
  log_both "================================================================================"
  log_both "Test completed with exit code: $exit_code"
  log_both "================================================================================"
  
  return $exit_code
}

################################################################################
# Post-test analysis
################################################################################

analyze_results() {
  local exit_code=$1
  
  log_both ""
  log_both "Analysis of results:"
  log_both ""
  
  # Check for key success markers
  local repo_cloned=0
  local image_selected=0
  local lease_created=0
  local server_launched=0
  local floating_ip=0
  
  if grep -q "Repository Analysis" "$LOG_FILE" && ! grep -q "✗" "$LOG_FILE" | head -1; then
    repo_cloned=1
    log_both "  ✓ Repository analysis step executed"
  fi
  
  if grep -q "Final Selection:" "$LOG_FILE"; then
    image_selected=1
    log_both "  ✓ Image selection completed"
    grep "Final Selection:" "$LOG_FILE" | tee -a "$LOG_FILE"
  fi
  
  if grep -q "Lease created:" "$LOG_FILE"; then
    lease_created=1
    log_both "  ✓ Lease created successfully"
    grep "Lease created:" "$LOG_FILE" | head -1 | tee -a "$LOG_FILE"
  fi
  
  if grep -q "✓ Server is ACTIVE" "$LOG_FILE"; then
    server_launched=1
    log_both "  ✓ Server launched and activated"
  fi
  
  if grep -q "✓ Using floating IP:" "$LOG_FILE" || grep -q "✓ Floating IP attached" "$LOG_FILE"; then
    floating_ip=1
    log_both "  ✓ Floating IP assigned"
    grep "✓ Using floating\|✓ Floating IP" "$LOG_FILE" | head -1 | tee -a "$LOG_FILE"
  fi
  
  log_both ""
  log_both "Step-by-step progress:"
  log_both "  Step 1 (Repo Analysis):  $([ $repo_cloned -eq 1 ] && echo "✓" || echo "✗")"
  log_both "  Step 2 (Image Select):   $([ $image_selected -eq 1 ] && echo "✓" || echo "✗")"
  log_both "  Step 5 (Create Lease):   $([ $lease_created -eq 1 ] && echo "✓" || echo "✗")"
  log_both "  Step 6 (Launch Server):  $([ $server_launched -eq 1 ] && echo "✓" || echo "✗")"
  log_both "  Step 7 (Floating IP):    $([ $floating_ip -eq 1 ] && echo "✓" || echo "✗")"
  log_both ""
  
  # Overall result
  if [ $exit_code -eq 0 ]; then
    log_success "Test PASSED (exit code 0)"
    return 0
  else
    log_error "Test FAILED (exit code $exit_code)"
    log_both ""
    log_both "Last 30 lines of output:"
    tail -30 "$LOG_FILE" | tee -a "$SUMMARY_FILE"
    return 1
  fi
}

################################################################################
# Main execution
################################################################################

main() {
  # Create log directory
  mkdir -p "$LOG_DIR"
  
  # Initialize log file
  {
    echo "Test started at: $(date)"
    echo "Repository: $REPO_URL"
    echo "Lease Duration: $LEASE_DURATION"
    echo "Site: $SITE"
    echo ""
  } > "$LOG_FILE"
  
  log_info "Test logs will be saved to: $LOG_FILE"
  log_info ""
  
  # Run preflight checks
  if ! run_preflight_checks; then
    log_error "Pre-flight checks failed"
    exit 1
  fi
  
  log_info ""
  log_info "All pre-flight checks passed. Starting provisioning..."
  log_info ""
  
  # Run the actual test
  run_test
  local test_exit_code=$?
  
  # Analyze results
  analyze_results $test_exit_code
  local analysis_exit_code=$?
  
  # Create summary file
  {
    echo "Provisioning Test Summary"
    echo "======================="
    echo ""
    echo "Repository: $REPO_URL"
    echo "Lease Duration: $LEASE_DURATION hour(s)"
    echo "Site: $SITE"
    echo "Timestamp: $(date)"
    echo "Exit Code: $test_exit_code"
    echo ""
    if [ $test_exit_code -eq 0 ]; then
      echo "Result: PASSED ✓"
    else
      echo "Result: FAILED ✗"
    fi
    echo ""
    echo "Full log: $LOG_FILE"
  } > "$SUMMARY_FILE"
  
  log_info ""
  log_info "Summary saved to: $SUMMARY_FILE"
  
  exit $analysis_exit_code
}

# Run main function
main
