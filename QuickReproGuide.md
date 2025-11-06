# Quick Repro Guide: Running EnvBoot APIs

This guide helps you (or a teammate) quickly reproduce the core API flows in a fresh checkout of this repo.

## Steps

**0. Set up Python environment and dependencies**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**1. Edit your OpenStack credentials**
- Copy `CHI-251467-openrc.sh` (or use your own OpenRC file)
- Edit it to match your OpenStack project/user info

**2. Source your OpenRC and authenticate**
```bash
source CHI-251467-openrc.sh
# Enter your OpenStack password if prompted
```

**3. Ensure Python can find the repo root**
```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
```

**4. Create a lease using API-2**
```bash
python src/api-core/api-2.py --zone uc --start "$(date -u -d '+3 minutes' '+%Y-%m-%d %H:%M')" --duration 45 --nodes 1
```
- You should see a JSON response with `"ok": true` and a `reservation_id`.

**5. (Optional) Override test parameters**
- You can override key settings (keypair, image, flavor, network, etc.) by exporting variables or prefixing the command:
```bash
KEY_NAME=mykey IMAGE="Ubuntu 22.04" FLAVOR=m1.large NETWORK=public bash scripts/test_api6_nova_physical_host.sh
```
- If not set, the script uses default values from `.env.example` or hardcoded defaults.
- You can use `openstack image list --column Name` for thelist of `IMAGE`.

**6. Run the full demo/test script**
```bash
bash scripts/test_api6_nova_physical_host.sh
```
- This exercises all 6 APIs in sequence (lease create, status, server launch, etc.)

Expected output example:
```bash
(.venv) cc@envagentplus:~/envagentplus/EnvAgent-plus$ bash scripts/test_api6_nova_physical_host.sh
[INFO] Step 1/6: Creating physical:host lease (start ~2 min, duration 45 min, 1 node)...
[INFO] ✓ Lease created successfully
[INFO]   Reservation ID: 397d77c5-e3e0-42ae-83d1-4680b210bb1d
[INFO]   Resource type: physical:host
[INFO]   Start: 2025-11-06T19:13:00Z
[INFO]   End: 2025-11-06T19:58:00Z
[INFO] Step 2/6: Waiting for lease to become ACTIVE (timeout: 5 minutes)...
[INFO] ✓ Lease is now ACTIVE
[INFO] Step 3/6: Launching baremetal instance via api-6 (Nova path with reservation hint)...
[INFO]   Image: CC-Ubuntu20.04
[INFO]   Flavor: baremetal
[INFO]   Network: sharednet1
[INFO]   Keypair: Chris
[INFO]   Wait timeout: 10 minutes
[INFO] ✓ Server launch succeeded
[INFO] Step 4/6: Extracting server details and SSH connection info...
[INFO]   Server ID: 1d08d848-fc79-4d6c-81bd-b5415bfb6ad2
[INFO]   Status: ACTIVE
[INFO]   Fixed IP: 10.140.82.190
[INFO]   Floating IP: <none>
[INFO]   SSH User: ubuntu
[INFO]   Key Name: Chris
[WARN] No floating IP assigned; using fixed IP (requires VPN or jump host)
[INFO] Step 5/6: Testing connectivity to 10.140.82.190...
[WARN] Server did not respond to ping (may be normal for baremetal provisioning)
[WARN] SSH may still work once cloud-init completes

================================================================
  SSH Connection Info
================================================================

  Server is ready for SSH access:

    ssh -o StrictHostKeyChecking=no -i ~/.ssh/Chris.pem ubuntu@10.140.82.190

  (Adjust the private key path as needed for your keypair 'Chris')

  Note: Using fixed IP. Ensure you're on the tenant network or VPN.

================================================================

[INFO] Step 6/6: Skipping cleanup - server and lease will remain active
[WARN] Remember to manually delete the lease when done:
[WARN]   python3 src/api-core/api-4.py --reservation-id 397d77c5-e3e0-42ae-83d1-4680b210bb1d --confirm


================================================================
  Test Summary
================================================================

  ✓ Lease created and became ACTIVE
  ✓ Baremetal instance launched via Nova (reservation hint)
  ✓ Server reached status: ACTIVE
  ✓ SSH connection info extracted
  ! Lease cleanup SKIPPED - server is still running

  Server details:
    - Lease ID: 397d77c5-e3e0-42ae-83d1-4680b210bb1d
    - Server ID: 1d08d848-fc79-4d6c-81bd-b5415bfb6ad2
    - IP: 10.140.82.190
    - SSH: ssh -i ~/.ssh/Chris.pem ubuntu@10.140.82.190

  To delete the lease when done:
    python3 src/api-core/api-4.py --reservation-id 397d77c5-e3e0-42ae-83d1-4680b210bb1d --confirm

  Logs available in:
    - /tmp/api2_out.json (lease creation)
    - /tmp/api3_out.json (lease status)
    - /tmp/api6_out.json (server launch)

================================================================

[INFO] All tests passed successfully!
```

## Notes
- All scripts expect OpenStack environment variables (OS_*) to be set (via OpenRC).
- If you see import errors for `envboot`, make sure you set `PYTHONPATH` as above.
- For troubleshooting, see `/tmp/api*_out.json` files after running the test script.
- You can use dry-run mode for most APIs by adding `--dry-run` to the command.

---

For more details, see the main README or docs in this repo.
