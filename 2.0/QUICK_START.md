# Quick Start Guide - EnvAgent-plus 2.0

## Installation (5 minutes)

### Step 1: Install Dependencies

```bash
cd /home/cc/EnvAgent-plus/2.0/src
pip install -r requirements.txt
```

### Step 2: Configure AI API

Create `.env` file with your AI credentials:

```bash
cat > .env << EOF
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=forge-your-actual-key-here
OPENAI_MODEL=OpenAI/gpt-4o
EOF
```

### Step 3: Set OpenStack Credentials

```bash
source ../config/CHI-251467-openrc.sh
# Enter your Chameleon password when prompted
```

## Basic Usage

### Example 1: Deploy PyTorch Examples

```bash
cd /home/cc/EnvAgent-plus/2.0/src
python provision_v2.py --repo https://github.com/pytorch/examples
```

This will:
1. ✓ Clone the repository
2. ✓ Analyze requirements (detects GPU/CUDA needs)
3. ✓ Select appropriate OS image (e.g., CC-Ubuntu22.04-CUDA)
4. ✓ Choose hardware (e.g., gpu_rtx_6000)
5. ✓ Create lease (AI determines duration)
6. ✓ Launch server
7. ✓ Assign floating IP
8. ✓ Display SSH connection info

**Expected time**: 15-40 minutes (mostly waiting for hardware)

### Example 2: Create New SSH Key

```bash
python provision_v2.py \
    --repo https://github.com/pytorch/examples \
    --create-key \
    --key-name my-ml-key
```

### Example 3: Custom Configuration

```bash
python provision_v2.py \
    --repo https://github.com/user/project \
    --lease-name my-experiment \
    --server-name gpu-worker \
    --node-type gpu_rtx_6000
```

## What You'll See

```
============================================================
Automated Hardware Provisioning Tool v2.0
============================================================
✓ Configuration loaded
✓ AI client initialized
✓ OpenStack connection established

============================================================
Step 1: Repository Analysis
============================================================
✓ Successfully cloned repository to: /tmp/pytorch-examples
✓ Repository requirements analysis complete:
  CPU: 4 cores
  RAM: 16 GB
  GPU: Required
  GPU Memory: 8 GB
  Disk: 50 GB
  Operating System: ubuntu 22.04
  CUDA: Required

============================================================
Step 2: Image Selection
============================================================
✓ Found 45 available CC-* images
✓ AI Stage 1: Selected 3 candidates
  Reasoning: Selected CUDA-enabled Ubuntu images matching version requirement
✓ Final Selection: CC-Ubuntu22.04-CUDA

============================================================
Step 3: SSH Key Management
============================================================
✓ Keypair exists: my-key

============================================================
Step 4: Network Configuration
============================================================
✓ Found network: sharednet1 (ID: a772a899-ff3d-420b-8b31-1c485092481a)

✓ Target node type: gpu_rtx_6000

============================================================
Step 5: Create Hardware Reservation
============================================================
✓ AI determined duration: 24 hours
  Reasoning: Standard ML training workload typically requires 12-24 hours

Creating lease:
  Name: auto-gpu_rtx_6000-202512041030
  Node Type: gpu_rtx_6000
  Start: 2025-12-04 10:32
  End: 2025-12-05 10:32

✓ Lease created: 7601f737-6c34-4dc4-b640-db13f44227c8

Waiting for lease to activate...
  Status: PENDING, waiting...
  Status: PENDING, waiting...
✓ Lease is ACTIVE
✓ Reservation ID: 74dcdd19-0408-4777-a97f-a544ab21fa6d

============================================================
Step 6: Launch Bare Metal Server
============================================================

Launching server:
  Name: auto-server-202512041030
  Image ID: 1052ba60-cbe6-45ad-91ac-6ad0807c6e23
  Key: my-key
  Network ID: a772a899-ff3d-420b-8b31-1c485092481a
  Reservation ID: 74dcdd19-0408-4777-a97f-a544ab21fa6d

✓ Server creation initiated: bafa4456-0ba0-420a-8932-08e6eb5547c0

Waiting for server to become ACTIVE...
(This may take 10-30 minutes for bare metal)
  Status: BUILD
  Status: BUILD
  Status: ACTIVE

✓ Server is ACTIVE

============================================================
Step 7: Assign Floating IP
============================================================
✓ Using floating IP: 192.5.87.31
✓ Floating IP attached

============================================================
✓ Provisioning Complete!
============================================================
Server Name: auto-server-202512041030
Server ID: bafa4456-0ba0-420a-8932-08e6eb5547c0
Lease ID: 7601f737-6c34-4dc4-b640-db13f44227c8
Reservation ID: 74dcdd19-0408-4777-a97f-a544ab21fa6d
Image: CC-Ubuntu22.04-CUDA
Node Type: gpu_rtx_6000
Floating IP: 192.5.87.31

SSH Connection:
  ssh ubuntu@192.5.87.31

✓ Info saved to: auto-server-202512041030_info.json
```

## Troubleshooting

### Issue: "Missing OS_AUTH_URL"

**Solution:**
```bash
source ../config/CHI-251467-openrc.sh
```

### Issue: "AI API key invalid"

**Solution:**
```bash
# Check your .env file
cat .env
# Update with correct key
nano .env
```

### Issue: "No available hosts"

**Solution:**
Try a different time or node type:
```bash
python provision_v2.py \
    --repo https://github.com/user/project \
    --node-type compute_cascadelake_r640
```

## Next Steps

After your server is ready:

1. **Connect via SSH:**
   ```bash
   ssh ubuntu@<floating-ip>
   ```

2. **Install your project:**
   ```bash
   git clone https://github.com/your/repo
   cd repo
   pip install -r requirements.txt
   ```

3. **Run your code:**
   ```bash
   python train.py
   ```

4. **Monitor resources:**
   ```bash
   nvidia-smi  # Check GPU usage
   htop        # Check CPU/RAM
   ```

## Cleanup

When done, delete resources to free up quota:

```bash
# Get info from saved JSON
cat auto-server-*.json

# Delete server
openstack server delete <server-id>

# Delete lease
openstack reservation lease delete <lease-id>

# Delete floating IP (optional)
openstack floating ip delete <floating-ip>
```

## Advanced Usage

See detailed documentation:
- `README.md` - Full user guide
- `USAGE_EXAMPLES.md` - More examples
- `VERSION_COMPARISON.md` - v1.0 vs v2.0

## Support

For help:
1. Check documentation in `src/*.md`
2. Review `INTEGRATION_GUIDE.md`
3. Consult parent directory's `envboot/` and `src/api-core/`

Happy provisioning! 🚀

