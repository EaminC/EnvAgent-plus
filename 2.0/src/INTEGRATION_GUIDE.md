# Integration Guide: 2.0 Provision Tool with Existing EnvAgent-plus

This guide explains how the new 2.0 provision tool integrates with the existing EnvAgent-plus infrastructure.

## Overview

The 2.0 provision tool builds upon the existing codebase:

```
EnvAgent-plus/
├── envboot/                    # Existing: OpenStack SDK wrappers
│   ├── osutil.py              # ✓ Used by v2.0
│   └── __init__.py
├── src/
│   ├── api-core/              # Existing: API tools (api-1 to api-6)
│   │   ├── api-1.py          # Capacity check
│   │   ├── api-2.py          # Lease creation
│   │   ├── api-6.py          # Server launch
│   │   └── ...
│   ├── provision.py           # NEW: v1.0 (CLI-based)
│   ├── provision_v2.py        # NEW: v2.0 (SDK-based)
│   ├── ai_client.py          # NEW: AI integration
│   ├── repo_analyzer.py      # NEW: Repo analysis
│   └── ...
```

## Component Integration

### 1. OpenStack Connection (`envboot/osutil.py`)

**Existing Functionality**:
- `conn()` - Returns authenticated OpenStack connection
- `blz()` - Returns Blazar client
- Supports OIDC authentication
- Handles .env files

**How v2.0 Uses It**:
```python
from envboot.osutil import conn, blz

# Get OpenStack connection
os_conn = conn()

# Use for operations
images = list(os_conn.compute.images())
server = os_conn.compute.create_server(...)

# Get Blazar client
blazar = blz()
lease = blazar.lease.create(...)
```

### 2. API Core Tools (`src/api-core/`)

**Existing Tools**:
- `api-1.py` - Check capacity
- `api-2.py` - Create reservation
- `api-3.py` - Check lease status
- `api-4.py` - Delete reservation
- `api-5.py` - Node allocation
- `api-6.py` - Launch servers

**How v2.0 Complements Them**:
The v2.0 tool provides an end-to-end workflow that:
- Uses similar patterns for JSON output
- Can call api-core tools via subprocess if needed
- Provides higher-level automation

**Example Integration**:
```python
# v2.0 could call existing tools
import subprocess
import json

# Use api-1 to check capacity before lease creation
result = subprocess.run(
    ['python3', 'api-core/api-1.py', 
     '--zone', 'uc', 
     '--start', start_time,
     '--duration', '1440'],
    capture_output=True,
    text=True
)
capacity = json.loads(result.stdout)
```

### 3. Shared Configuration

**Existing**: OpenRC files in `config/`
**New**: `.env` files for AI credentials

**Combined Setup**:
```bash
# 1. Source OpenStack credentials
source config/CHI-251467-openrc.sh

# 2. Create .env for AI settings
cat > src/.env << EOF
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=OpenAI/gpt-4o
EOF

# 3. Run provision tool
cd src
python provision_v2.py --repo https://github.com/user/project
```

## Usage Patterns

### Pattern 1: Full Automation (New)

Use the provision tool for complete end-to-end automation:

```bash
python provision_v2.py \
    --repo https://github.com/pytorch/examples \
    --create-key \
    --lease-name ml-training
```

### Pattern 2: Step-by-Step (Existing + New)

Use api-core tools for individual steps:

```bash
# 1. Check capacity
python api-core/api-1.py --zone uc --start "2025-12-05 10:00" --duration 1440

# 2. Create lease
python api-core/api-2.py --zone uc --start "2025-12-05 10:00" --duration 1440 --nodes 1

# 3. Use provision tool for analysis and launch
python provision_v2.py --repo https://github.com/user/project --lease-name <lease-id>
```

### Pattern 3: Hybrid Approach

Mix and match based on needs:

```bash
# Use provision tool for analysis
python provision_v2.py --repo https://github.com/user/project --skip-launch

# Use api-6 for custom launch
python api-core/api-6.py \
    --reservation-id <res-id> \
    --image CC-Ubuntu22.04-CUDA \
    --flavor baremetal \
    --network sharednet1 \
    --key-name my-key
```

## Data Flow Integration

### Existing Flow (api-core):
```
api-1 → capacity check → JSON output
    ↓
api-2 → create lease → JSON output
    ↓
api-3 → wait for ACTIVE → JSON output
    ↓
api-6 → launch server → JSON output
```

### New Flow (provision tool):
```
GitHub repo → analyze → requirements
    ↓
Requirements → AI → image selection
    ↓
Image + requirements → AI → resource selection
    ↓
envboot.osutil → OpenStack SDK → lease creation
    ↓
Lease → envboot.osutil → server launch
    ↓
Server → floating IP → complete
```

### Combined Flow:
```
provision_v2.py internally:
    ├── Uses envboot.osutil (existing)
    ├── Could call api-1.py for capacity check
    ├── Uses blazar client directly (like api-2.py)
    ├── Uses SDK directly (like api-6.py)
    └── Adds AI-driven decision making (new)
```

## Extension Points

### Add Custom AI Models

Edit `src/config.py`:
```python
OPENAI_MODEL=OpenAI/gpt-4o-mini  # Faster model
OPENAI_MODEL=OpenAI/o1-preview   # More capable model
```

### Add Custom Node Selection

Create `src/custom_selector.py`:
```python
def select_node_type(requirements):
    # Custom logic
    if requirements.get('memory_gb', 0) > 128:
        return "compute_cascadelake_r640_384gb"
    # ... more logic
    return "compute_haswell"
```

Then import in `provision_v2.py`:
```python
from custom_selector import select_node_type
node_type = select_node_type(requirements)
```

### Add Pre/Post-Launch Hooks

Modify `provision_v2.py`:
```python
def pre_launch_hook(server_name, image_id):
    """Called before server creation"""
    print(f"About to launch: {server_name}")
    # Custom logic here
    
def post_launch_hook(server_id, floating_ip):
    """Called after server becomes ACTIVE"""
    print(f"Server ready: {floating_ip}")
    # E.g., configure DNS, notify team, etc.
```

## Testing Integration

### Test with Existing Tools

```bash
# 1. Test api-core tools work
python api-core/api-1.py --zone uc --start "2025-12-06 10:00" --duration 60 --dry-run

# 2. Test new provision tool
python provision_v2.py --repo https://github.com/pytorch/examples --skip-repo-clone --dry-run

# 3. Test full integration (no dry-run)
python provision_v2.py --repo https://github.com/pytorch/examples
```

### Compatibility Matrix

| Component | v1.0 provision.py | v2.0 provision_v2.py | api-core tools |
|-----------|------------------|---------------------|----------------|
| Uses envboot.osutil | ✗ | ✓ | ✓ |
| Uses OpenStack CLI | ✓ | ✗ | Varies |
| JSON output format | Basic | Compatible | Structured |
| Can call each other | ✗ | ✓ | ✓ |

## Troubleshooting Integration

### Issue: Import errors from envboot

**Problem**:
```python
ImportError: cannot import name 'conn' from 'envboot.osutil'
```

**Solution**:
```bash
# Ensure parent directory is in PYTHONPATH
export PYTHONPATH=/home/cc/EnvAgent-plus:$PYTHONPATH

# Or run from correct directory
cd /home/cc/EnvAgent-plus/src
python provision_v2.py ...
```

### Issue: OpenStack credentials not found

**Problem**:
```
KeyError: 'OS_AUTH_URL'
```

**Solution**:
```bash
# Source the OpenRC file first
source ../config/CHI-251467-openrc.sh

# Verify
echo $OS_AUTH_URL
```

### Issue: Blazar client errors

**Problem**:
```
AttributeError: 'Client' object has no attribute 'lease'
```

**Solution**:
```bash
# Update python-blazarclient
pip install --upgrade python-blazarclient

# Verify version
pip show python-blazarclient
```

## Best Practices

### 1. Use v2.0 for New Workflows

When creating new automation:
```bash
python provision_v2.py --repo <url>  # Preferred
```

### 2. Use api-core for Granular Control

When you need fine-grained control:
```bash
python api-core/api-2.py --zone uc ...  # Specific operations
```

### 3. Combine When Appropriate

```bash
# Check capacity first
python api-core/api-1.py --zone uc --start "2025-12-06 10:00" --duration 1440

# If capacity is good, provision
python provision_v2.py --repo https://github.com/user/project
```

## Future Enhancements

Potential improvements to integration:

1. **Unified CLI**: Create a single entry point
   ```bash
   envboot provision --repo <url>
   envboot capacity --zone uc
   envboot launch --lease-id <id>
   ```

2. **Shared State**: Use common state file
   ```python
   # ~/.envboot/state.json
   {
     "last_lease": "abc123",
     "last_server": "xyz789",
     "preferences": {...}
   }
   ```

3. **Plugin System**: Allow custom extensions
   ```python
   # ~/.envboot/plugins/custom.py
   def on_server_ready(server_info):
       # Custom logic
       pass
   ```

## Conclusion

The 2.0 provision tool is designed to complement, not replace, the existing infrastructure. It:

- ✓ Reuses `envboot/osutil.py` for OpenStack access
- ✓ Follows similar patterns as `api-core/` tools
- ✓ Can interoperate with existing tools
- ✓ Adds AI-driven automation on top

Use it as a high-level workflow orchestrator while keeping the flexibility of lower-level api-core tools.

