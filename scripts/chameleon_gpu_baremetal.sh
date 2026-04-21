#!/usr/bin/env bash
set -euo pipefail

# Usage example:
#   source config/CHI-251467-openrc-2.sh
#   bash scripts/chameleon_gpu_baremetal.sh
#
# Optional overrides (env vars):
#   LEASE_NAME=my-lease
#   LEASE_HOURS=4
#   NODE_TYPE=gpu_rtx_6000
#   IMAGE=CC-Ubuntu20.04
#   FLAVOR=baremetal
#   NETWORK_NAME=sharednet1
#   KEY_NAME=Chris
#   SECURITY_GROUP=default
#   SSH_USER=cc
#   SERVER_NAME=gpu-node-1

LEASE_NAME="${LEASE_NAME:-gpu-lease}"
LEASE_HOURS="${LEASE_HOURS:-4}"
NODE_TYPE="${NODE_TYPE:-}"
IMAGE="${IMAGE:-CC-Ubuntu20.04}"
FLAVOR="${FLAVOR:-baremetal}"
NETWORK_NAME="${NETWORK_NAME:-sharednet1}"
KEY_NAME="${KEY_NAME:-Chris}"
SECURITY_GROUP="${SECURITY_GROUP:-default}"
SSH_USER="${SSH_USER:-cc}"
SERVER_NAME="${SERVER_NAME:-gpu-baremetal-$(date +%Y%m%d-%H%M%S)}"

LEASE_WAIT_TIMEOUT="${LEASE_WAIT_TIMEOUT:-1800}"
SERVER_WAIT_TIMEOUT="${SERVER_WAIT_TIMEOUT:-3600}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"

NODE_TYPE_CANDIDATES=(
  gpu_h100
  gpu_a100
  gpu_mi250
  gpu_rtx_6000
  gpu_v100
  gpu_p100
)

log() {
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd openstack
need_cmd jq

if [[ -z "${OS_AUTH_URL:-}" ]]; then
  echo "OpenStack credentials are not loaded. Source your OpenRC first." >&2
  exit 1
fi

log "Checking OpenStack auth token"
openstack token issue >/dev/null

log "Resolving network ID for ${NETWORK_NAME}"
NETWORK_ID="$(openstack network show "$NETWORK_NAME" -f value -c id)"

if ! openstack keypair show "$KEY_NAME" >/dev/null 2>&1; then
  FALLBACK_KEY="$(openstack keypair list -f value -c Name | head -n 1 || true)"
  if [[ -z "$FALLBACK_KEY" ]]; then
    echo "Requested keypair '${KEY_NAME}' not found and no keypairs exist in this project." >&2
    echo "Create one first: openstack keypair create <name> > ~/.ssh/<name>.pem" >&2
    exit 1
  fi
  log "Keypair '${KEY_NAME}' not found; using '${FALLBACK_KEY}'"
  KEY_NAME="$FALLBACK_KEY"
fi

find_reusable_lease_id() {
  local id status
  while IFS= read -r id; do
    status="$(openstack reservation lease show "$id" -f value -c status 2>/dev/null || true)"
    case "$status" in
      ACTIVE|PENDING|STARTING|CREATING|UPDATING)
        echo "$id"
        return 0
        ;;
    esac
  done < <(openstack reservation lease list -f json | jq -r --arg n "$LEASE_NAME" '.[] | select(.name == $n) | .id')
  return 1
}

create_lease_with_type() {
  local node_type="$1"
  local start_date end_date reservation_arg
  start_date="$(date -u '+%Y-%m-%d %H:%M')"
  end_date="$(date -u -d "+${LEASE_HOURS} hours" '+%Y-%m-%d %H:%M')"

  reservation_arg="min=1,max=1,resource_type=physical:host,resource_properties=[\"=\", \"\$node_type\", \"${node_type}\"]"

  openstack reservation lease create \
    --reservation "$reservation_arg" \
    --start-date "$start_date" \
    --end-date "$end_date" \
    "$LEASE_NAME" -f json
}

LEASE_ID=""
RESERVATION_ID=""
SELECTED_NODE_TYPE=""

if LEASE_ID="$(find_reusable_lease_id)"; then
  log "Reusing existing lease: $LEASE_ID (name=${LEASE_NAME})"
  SELECTED_NODE_TYPE=""
else
  log "No reusable lease named ${LEASE_NAME}. Creating a new lease."
  if [[ -n "$NODE_TYPE" ]]; then
    NODE_TYPE_CANDIDATES=("$NODE_TYPE")
  fi

  for t in "${NODE_TYPE_CANDIDATES[@]}"; do
    log "Trying lease creation with node_type=${t} (GPU=1, high RAM preferred by type order)"
    set +e
    LEASE_JSON="$(create_lease_with_type "$t" 2>&1)"
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
      candidate_lease_id="$(printf '%s' "$LEASE_JSON" | jq -r '.id // empty' 2>/dev/null || true)"
      if [[ -n "$candidate_lease_id" ]]; then
        LEASE_ID="$candidate_lease_id"
        SELECTED_NODE_TYPE="$t"
        log "Lease created: $LEASE_ID"
        break
      fi
    fi
    log "Lease creation failed for ${t}; trying next candidate"
  done

  if [[ -z "$LEASE_ID" ]]; then
    echo "Failed to create any lease. Last CLI output:" >&2
    echo "$LEASE_JSON" >&2
    exit 1
  fi
fi

log "Waiting for lease to become ACTIVE"
lease_start_epoch="$(date +%s)"
while true; do
  LEASE_STATUS="$(openstack reservation lease show "$LEASE_ID" -f value -c status)"
  if [[ "$LEASE_STATUS" == "ACTIVE" ]]; then
    break
  fi
  now="$(date +%s)"
  if (( now - lease_start_epoch > LEASE_WAIT_TIMEOUT )); then
    echo "Timed out waiting for lease ACTIVE. Current status: ${LEASE_STATUS}" >&2
    exit 1
  fi
  log "Lease status=${LEASE_STATUS}; sleeping ${POLL_INTERVAL}s"
  sleep "$POLL_INTERVAL"
done

LEASE_SHOW_JSON="$(openstack reservation lease show "$LEASE_ID" -f json)"
RESERVATION_ID="$(
  printf '%s' "$LEASE_SHOW_JSON" | jq -r '
    .reservations as $r |
    if ($r | type) == "array" then
      ($r[0].id // empty)
    elif ($r | type) == "object" then
      ($r.id // empty)
    elif ($r | type) == "string" then
      (
        ($r | fromjson) as $jr |
        if ($jr | type) == "array" then
          ($jr[0].id // empty)
        elif ($jr | type) == "object" then
          ($jr.id // empty)
        else
          empty
        end
      )
    else
      empty
    end
  '
)"

if [[ -z "$RESERVATION_ID" || "$RESERVATION_ID" == "null" ]]; then
  echo "Could not extract reservation ID from lease: $LEASE_ID" >&2
  exit 1
fi

log "Launching server: ${SERVER_NAME}"
SERVER_JSON="$(openstack server create "$SERVER_NAME" \
  --flavor "$FLAVOR" \
  --image "$IMAGE" \
  --nic net-id="$NETWORK_ID" \
  --key-name "$KEY_NAME" \
  --security-group "$SECURITY_GROUP" \
  --hint reservation="$RESERVATION_ID" \
  -f json)"

SERVER_ID="$(printf '%s' "$SERVER_JSON" | jq -r '.id')"

if [[ -z "$SERVER_ID" || "$SERVER_ID" == "null" ]]; then
  echo "Failed to create server or parse server ID." >&2
  echo "$SERVER_JSON" >&2
  exit 1
fi

log "Waiting for server to become ACTIVE"
server_start_epoch="$(date +%s)"
while true; do
  SERVER_STATUS="$(openstack server show "$SERVER_ID" -f value -c status)"
  if [[ "$SERVER_STATUS" == "ACTIVE" ]]; then
    break
  fi
  if [[ "$SERVER_STATUS" == "ERROR" ]]; then
    echo "Server entered ERROR state." >&2
    openstack server show "$SERVER_ID"
    exit 1
  fi
  now="$(date +%s)"
  if (( now - server_start_epoch > SERVER_WAIT_TIMEOUT )); then
    echo "Timed out waiting for server ACTIVE. Current status: ${SERVER_STATUS}" >&2
    exit 1
  fi
  log "Server status=${SERVER_STATUS}; sleeping ${POLL_INTERVAL}s"
  sleep "$POLL_INTERVAL"
done

log "Ensuring floating IP is attached"
FLOATING_IP="$(openstack floating ip list --status DOWN -f value -c "Floating IP Address" | head -n 1 || true)"

if [[ -z "$FLOATING_IP" ]]; then
  EXTERNAL_NET="$(openstack network list --external -f value -c Name | head -n 1)"
  if [[ -z "$EXTERNAL_NET" ]]; then
    echo "No external network available for floating IP allocation." >&2
    exit 1
  fi
  FLOATING_IP="$(openstack floating ip create "$EXTERNAL_NET" -f value -c floating_ip_address)"
fi

openstack server add floating ip "$SERVER_ID" "$FLOATING_IP"

log "Done"
echo ""
echo "Lease ID:        $LEASE_ID"
echo "Reservation ID:  $RESERVATION_ID"
echo "Node type:       ${SELECTED_NODE_TYPE:-unknown/reused}"
echo "Server ID:       $SERVER_ID"
echo "Public IP:       $FLOATING_IP"
echo "SSH command:     ssh -i ~/.ssh/${KEY_NAME}.pem ${SSH_USER}@${FLOATING_IP}"
