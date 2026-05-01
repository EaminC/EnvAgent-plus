# KVM Provisioning Pipeline Patch - Complete Status & Next Steps

## Executive Summary

I've successfully identified and documented the **exact mismatch** between your KVM code and the correct python-chi workflow. The root cause: your current code treats KVM as a bare-metal fallback using direct Nova VM launch, but KVM@TACC requires **flavor-based Blazar leases through python-chi** — a completely separate provisioning path.

---

## What's Completed ✅

### 1. Root Cause Analysis
**Your current code (BROKEN for KVM@TACC):**
- Uses Blazar with `resource_type='physical:host'` and `node_type` filters (bare metal semantics)
- When that fails, falls back to direct Nova VM launch without any reservation
- Result: VM enters ERROR state due to missing security groups, floating IP setup, and reservation binding

**Correct approach (python-chi):**
- Uses Blazar with `add_flavor_reservation(flavor_name)` — flavor-based, not node-type-based
- Launches server with `chi.server.Server(flavor_name=reserved_flavor.name)`
- Explicitly configures security groups and floating IP via chi_network
- Result: ACTIVE VM with working SSH access

**See:** [/tmp/kvm_mismatch_analysis.md](file:///tmp/kvm_mismatch_analysis.md)

### 2. Python-chi Imports Added
**File:** `2.0/src/provision_v2.py` (lines 25-32)

```python
# Import python-chi for KVM provisioning
try:
    from chi import context, lease as chi_lease, server as chi_server, network as chi_network
    PYTHON_CHI_AVAILABLE = True
except ImportError:
    PYTHON_CHI_AVAILABLE = False
    print("⚠ WARNING: python-chi not available; KVM provisioning will be limited")
```

✅ **Status:** Already applied

### 3. Five New KVM Functions
**Location in provision_v2.py:** Insert after `_first_value()` function (~line 607) and before `_find_baremetal_node()` (~line 650)

**Source:** [KVM_FUNCTIONS.py](KVM_FUNCTIONS.py) — ready to copy/paste

**Functions:**

1. **`discover_kvm_flavors_with_chi()`** — Uses python-chi to list GPU/CPU flavors
   - Calls `context.use_site(site)` and `context.choose_project()`
   - Lists flavors with `chi_server.list_flavors(gpu=gpu_required, reservable=True)`
   - Returns list of flavor objects

2. **`select_kvm_flavor_with_ai()`** — AI selects best flavor from list
   - Handles single-flavor case
   - Builds prompt with flavor specs
   - Returns selected flavor object

3. **`create_kvm_lease_with_flavor()`** — Creates Blazar flavor-based lease
   - Uses AI to determine duration
   - Calls `chi_lease.Lease()` and `add_flavor_reservation()`
   - Waits for lease to become ACTIVE
   - Returns (lease_id, lease_object)

4. **`launch_kvm_server_with_reserved_flavor()`** — Launches server with reserved flavor
   - Gets reserved flavor from lease: `lease.get_reserved_flavors().pop()`
   - Creates server: `chi_server.Server(flavor_name=reserved_flavor.name, image_name=image_name)`
   - Waits for ACTIVE status
   - Returns (server_id, server_obj)

5. **`configure_kvm_server_access()`** — Sets up SSH and floating IP
   - Creates/assigns "Allow SSH" security group
   - Calls `server.associate_floating_ip()`
   - Returns (floating_ip, sg_id)

✅ **Status:** Functions implemented and ready to copy

---

## What Remains ⏳

### Step 1: Copy Five KVM Functions
**What to do:**
1. Open [KVM_FUNCTIONS.py](KVM_FUNCTIONS.py)
2. Copy all five functions (after the docstring)
3. Paste into `2.0/src/provision_v2.py` after line ~607 (`def _first_value()...` function)
4. Verify indentation is correct (should be at module level, not indented)

**Expected result:** File has all 5 new functions; `mcp_pylance` syntax check passes

### Step 2: Add Site-Aware Provisioning Logic to main()
**What to replace:** Lines 1235-1330 in `provision_v2.py` (the old KVM fallback try-except block)

**New logic structure:**
```python
# Step 5: Provisioning - KVM vs Bare Metal based on site
lease_name_base = args.lease_name or f"auto-{datetime.now().strftime('%Y%m%d%H%M')}"
server_name = args.server_name or f"auto-server-{datetime.now().strftime('%Y%m%d%H%M')}"

# Initialize provisioning result variables
lease_id = None
reservation_id = None
server_id = None
server_info = None
server_obj = None
floating_ip = None
provision_snapshot = {}
provisioning_type = None

# Check if this is a KVM site
is_kvm_site = args.site and ("kvm" in args.site.lower())

if is_kvm_site:
    # ===== KVM PROVISIONING PATH =====
    # ... KVM functions calls ...
    # See PATCH_IMPLEMENTATION_GUIDE.md for full code

else:
    # ===== BARE METAL PROVISIONING PATH =====
    # ... existing bare metal code (unchanged) ...
```

**Key points:**
- Remove all old `is_kvm_fallback` logic
- Detect KVM site by checking if "kvm" is in `args.site`
- Call new KVM functions sequentially
- Existing bare metal code stays the same

**See full code:** [PATCH_IMPLEMENTATION_GUIDE.md](PATCH_IMPLEMENTATION_GUIDE.md) (search for "Replace provisioning logic")

### Step 3: Update Final Summary References
**What to replace:** Lines 1476 and 1502 (references to `is_kvm_fallback`)

**OLD:**
```python
print(f"Provisioning Type: {'KVM VM (Tier 4 Fallback)' if is_kvm_fallback else 'Bare Metal (Blazar)'}")
...
'provisioning_type': 'kvm_vm' if is_kvm_fallback else 'bare_metal',
```

**NEW:**
```python
prov_type_display = "KVM (python-chi)" if provisioning_type == "kvm_chi" else "Bare Metal (Blazar)" if provisioning_type == "bare_metal" else provisioning_type or "Unknown"
print(f"Provisioning Type: {prov_type_display}")
...
'provisioning_type': provisioning_type or 'unknown',
```

**Why:** `provisioning_type` is set by the new KVM and bare metal paths; `is_kvm_fallback` no longer exists

---

## Testing Instructions

### 1. Syntax Check
```bash
cd /home/cc/EnvAgent-plus
python -m py_compile 2.0/src/provision_v2.py
```
Expected: No output (success)

### 2. KVM Provisioning Test
```bash
cd /home/cc/EnvAgent-plus
python 2.0/src/provision_v2.py \
  --repo https://github.com/yrcong/RelTR \
  --site KVM@TACC \
  --lease-duration 24 \
  --create-key
```

Expected output sequence:
```
============================================================
Automated Hardware Provisioning Tool v2.0
============================================================
✓ Configuration loaded
✓ AI client initialized
✓ OpenStack connection established

...

============================================================
KVM Provisioning Flow
============================================================
✓ Site detected: KVM@TACC (KVM)

============================================================
KVM Flavor Discovery (via python-chi)
============================================================
→ Setting site context: KVM@TACC
✓ Site context established
→ Querying GPU-capable flavors...
✓ Found N GPU-capable reservable flavors

✓ AI selected flavor: [flavor_name]

Step 5: Create KVM Flavor Reservation
============================================================
✓ Lease created: [lease_id]
✓ Lease is ACTIVE
✓ Reserved flavors confirmed

Step 6: Launch KVM Server
============================================================
→ Using reserved flavor: [flavor_name]
  Status: BUILD
  Status: ACTIVE
✓ KVM server is ACTIVE

Step 7: Configure KVM Server Access
============================================================
→ Configuring SSH security group...
✓ Security group assigned
→ Associating floating IP...
✓ Floating IP assigned: [IP_ADDRESS]

✓ Provisioning Complete!
✓ KVM (python-chi)
Server Name: auto-server-[timestamp]
Server ID: [server_id]
Lease ID: [lease_id]
Image: [image_name]
Floating IP: [IP_ADDRESS]

SSH Connection:
  ssh ubuntu@[IP_ADDRESS]

✓ Info saved to: auto-server-[timestamp]_info.json
```

### 3. Bare Metal Test (CHI@TACC)
```bash
python 2.0/src/provision_v2.py \
  --repo https://github.com/yrcong/RelTR \
  --site uc \
  --lease-duration 24
```

Expected: Existing bare metal flow works unchanged

---

## Files Created as Reference

1. **[kvm_mismatch_analysis.md](/tmp/kvm_mismatch_analysis.md)** — Detailed mismatch explanation
2. **[PATCH_IMPLEMENTATION_GUIDE.md](PATCH_IMPLEMENTATION_GUIDE.md)** — Full code snippets with line numbers
3. **[KVM_FUNCTIONS.py](KVM_FUNCTIONS.py)** — Ready-to-copy KVM functions
4. **[gpu_instance.ipynb](gpu_instance.ipynb)** (attached) — Reference notebook showing correct pattern

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| `python-chi not available` | Library not installed | `pip install python-chi` |
| `KVM instance enters ERROR after BUILD` | No security group | Now handled by `configure_kvm_server_access()` |
| `No reservable flavors found` | Site context not set | Now handled by `context.use_site()` and `context.choose_project()` |
| `Lease creation failed` | Not using flavor reservation | Now using `add_flavor_reservation(flavor_name)` |
| `VM unreachable after launch` | No floating IP assigned | Now handled by `server.associate_floating_ip()` |

---

## Summary of Changes

| Component | Status | Impact |
|-----------|--------|--------|
| Python-chi imports | ✅ DONE | Graceful degradation if unavailable |
| 5 KVM functions | ✅ DONE | Ready to copy/paste |
| Site detection logic | ⏳ PENDING | 30 lines of code in main() |
| Bare metal flow | ✅ UNCHANGED | Existing code stays the same |
| Final output logging | ⏳ PENDING | 3 line changes for provisioning_type |

**Estimated effort to complete:** 20-30 minutes (copy functions + update main())

---

## Next Action

1. Copy the 5 functions from [KVM_FUNCTIONS.py](KVM_FUNCTIONS.py) into `provision_v2.py`
2. Update the provisioning logic in `main()` using [PATCH_IMPLEMENTATION_GUIDE.md](PATCH_IMPLEMENTATION_GUIDE.md)
3. Run syntax check
4. Test on KVM@TACC with `--site KVM@TACC`

Would you like me to:
- A) Apply the remaining changes automatically (steps 1-3)?
- B) Provide more detailed code snippets for manual copy-paste?
- C) Help debug any specific errors during implementation?
