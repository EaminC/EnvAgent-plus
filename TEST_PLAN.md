# EnvAgent-plus Provisioning Test Plan

## Quick Start

### Prerequisites
Before running tests, ensure you have:

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Load Chameleon credentials
source ./config/CHI-251467-openrc.sh
# Enter your Chameleon CLI password when prompted

# 3. Verify Forge API is working (optional)
python ./2.0/api/forge.py
```

### Running the Test

```bash
# Make test script executable
chmod +x test_provision.sh

# Run the default test (PyTorch examples, 1-hour lease)
./test_provision.sh

# Or with custom parameters
./test_provision.sh \
  --repo https://github.com/pytorch/examples \
  --duration 1 \
  --site uc
```

## Test Details

### What Gets Tested

The script validates the following workflow:

1. **Pre-flight Checks** (automatic)
   - Virtual environment activated
   - Chameleon credentials available
   - Provision script exists
   - Configuration file (.env) present

2. **Repository Analysis**
   - Clone GitHub repo
   - Analyze environment requirements
   - Detect GPU/CUDA needs

3. **Image Selection**
   - Query available CC-* images
   - AI selects candidates
   - Final selection based on requirements

4. **Resource Discovery**
   - List available node types
   - AI selects appropriate hardware
   - Filter by availability

5. **Lease Creation**
   - Create Blazar reservation
   - AI determines lease duration
   - Wait for lease to activate

6. **Server Launch**
   - Create bare-metal server
   - Wait for ACTIVE status
   - May take 10-30 minutes

7. **Floating IP**
   - Assign external IP
   - Enable SSH access

### Output and Logging

- **Console Output**: Real-time progress with colored markers
- **Log File**: Full detailed output saved to `test_logs/provision_TIMESTAMP.log`
- **Summary File**: Quick overview saved to `test_logs/provision_TIMESTAMP_summary.txt`

Example output:
```
[INFO] Running pre-flight checks...
[✓] Virtual environment is active
[✓] Chameleon credentials loaded
[✓] Provision script found

[INFO] Starting provisioning process...
Command: python 2.0/src/provision_v2.py --repo https://github.com/pytorch/examples --lease-duration 1 --site uc

[Full provisioning output...]

Test completed with exit code: 0

Analysis of results:
  ✓ Repository analysis step executed
  ✓ Image selection completed
  ✓ Lease created successfully
  ✓ Server launched and activated
  ✓ Floating IP assigned
```

## Test Repositories

Currently configured for: **PyTorch examples**
- Repo: `https://github.com/pytorch/examples`
- Expected: GPU requirement detected
- Expected: CUDA image selected
- Expected: gpu_* node type selected

### Future: Testing Multiple Repositories

To extend this to multiple repos, you would run:

```bash
# Create a test suite file
cat > test_repos.txt << EOF
https://github.com/pytorch/examples
https://github.com/tensorflow/models
https://github.com/openai/gpt-2
EOF

# Loop through repos
while IFS= read -r repo; do
  echo "Testing: $repo"
  ./test_provision.sh --repo "$repo" --duration 1 --site uc
done < test_repos.txt
```

## Interpreting Results

### Success Indicators
- Exit code 0
- All 7 steps completed
- SSH connection available via floating IP

### Common Issues

**Pre-flight check fails:**
- Activate venv: `source venv/bin/activate`
- Load credentials: `source ./config/CHI-251467-openrc.sh`

**Repo clone fails:**
- Check GitHub URL is accessible
- Verify git is installed
- Check network connectivity

**Image selection shows "No candidates found":**
- Check available images: `openstack image list`
- Verify AI client is working

**Lease creation fails with "Not enough resources":**
- Site may be full
- Try different node type
- Check Chameleon status page

**Server launch timeout:**
- Bare metal provisioning takes 10-30 minutes
- Check Chameleon web interface
- Monitor with: `openstack server show <server-id>`

## Monitoring During Test

In another terminal, monitor the deployment:

```bash
# Watch lease status
watch -n 5 openstack reservation lease list

# Watch server status
watch -n 5 openstack server list

# Get specific server details
openstack server show <server-id>
```

## Log Files

All test runs are logged to `test_logs/`:

```
test_logs/
├── provision_20251216_143022.log          # Full detailed log
├── provision_20251216_143022_summary.txt  # Quick summary
├── provision_20251216_150515.log
└── provision_20251216_150515_summary.txt
```

View logs:
```bash
# Last test summary
cat test_logs/*.txt | tail -20

# Follow last test in real-time
tail -f test_logs/*.log
```

## Next Steps

1. Run the single-repo test to observe current behavior
2. Document any errors encountered
3. Identify issues to fix in provision_v2.py
4. Iterate and re-test
5. Once stable, extend to multiple repositories

## Technical Notes

- Script uses `set -o pipefail` to catch errors in piped commands
- Log files capture both stdout and stderr
- Colors used: Green (✓), Red (✗), Yellow (⚠), Blue ([INFO])
- No code modifications - observation mode only
- Tests run sequentially (not in parallel)
- Timestamps use format: YYYYMMDD_HHMMSS
