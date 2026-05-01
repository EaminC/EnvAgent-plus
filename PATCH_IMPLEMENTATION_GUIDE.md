# KVM Provisioning Pipeline Patch - Implementation Summary

## Status
I've begun implementing the KVM provisioning patch but encountered merge conflicts due to the complexity of replacing the nested try-except blocks. Here's what needs to be done:

## Files to Modify

### 1. provision_v2.py - Add Imports
```python
# At top of file (after existing imports):
try:
    from chi import context, lease as chi_lease, server as chi_server, network as chi_network
    PYTHON_CHI_AVAILABLE = True
except ImportError:
    PYTHON_CHI_AVAILABLE = False
    print("⚠ WARNING: python-chi not available; KVM provisioning will be limited")
```

### 2. provision_v2.py - Add Four New Functions

**Function A: Discover KVM Flavors**
```python
def discover_kvm_flavors_with_chi(ai_client: AIClient, requirements: dict, site: str = "KVM@TACC"):
    """Discover available GPU flavors at KVM site using python-chi."""
    # See full implementation below (Function A)
```

**Function B: Select KVM Flavor with AI**
```python
def select_kvm_flavor_with_ai(ai_client: AIClient, requirements: dict, available_flavors: list):
    """Use AI to select best flavor from available KVM flavors."""
    # See full implementation below (Function B)
```

**Function C: Create KVM Lease with Flavor Reservation**
```python
def create_kvm_lease_with_flavor(ai_client: AIClient, requirements: dict, 
                                 flavor_name: str, lease_name: str,
                                 duration_hours: int = None, start_delay_minutes: int = 2):
    """Create KVM flavor-based Blazar lease via python-chi."""
    # See full implementation below (Function C)
```

**Function D: Launch KVM Server with Reserved Flavor**
```python
def launch_kvm_server_with_reserved_flavor(lease_obj, image_name: str, 
                                           server_name: str, key_name: str = None):
    """Launch KVM server using reserved flavor from lease."""
    # See full implementation below (Function D)
```

**Function E: Configure KVM Server Access**
```python
def configure_kvm_server_access(server_obj, key_name: str = None):
    """Configure KVM server for SSH access and assign floating IP."""
    # See full implementation below (Function E)
```

### 3. provision_v2.py - Replace Provisioning Logic in main()

Replace the entire section from `# Step 5: Create lease with fallback chain` through `# Step 7: Floating IP` with new site-aware branching logic.

**OLD CODE (lines ~1235-1330):** Remove entirely
```python
# Step 5: Create lease with fallback chain (including KVM VMs as Tier 4)
lease_name_base = args.lease_name or f"auto-{datetime.now().strftime('%Y%m%d%H%M')}"
server_name = args.server_name or f"auto-server-{datetime.now().strftime('%Y%m%d%H%M')}"

# Initialize provisioning result variables
lease_id = None
reservation_id = None
server_id = None
server_info = None
is_kvm_fallback = False
provision_snapshot = {}

# Try bare-metal with Blazar
try:
    # ... all the old try-except blocks for KVM fallback
except Exception as blazar_error:
    # ... KVM fallback code ...

# Step 7: Floating IP
floating_ip = None
if not args.no_floating_ip:
    floating_ip = assign_floating_ip(os_conn, server_id)
```

**NEW CODE (replaces above):** Insert this
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
    print(f"\n{'='*60}")
    print(f"KVM Provisioning Flow")
    print(f"{'='*60}")
    print(f"✓ Site detected: {args.site} (KVM)")
    
    if not PYTHON_CHI_AVAILABLE:
        raise Exception("python-chi library required for KVM provisioning (run: pip install python-chi)")
    
    try:
        # Step 5a: Discover available KVM flavors
        available_flavors = discover_kvm_flavors_with_chi(
            ai_client, requirements, site=args.site
        )
        
        if not available_flavors:
            raise Exception("No reservable flavors available at KVM site")
        
        # Step 5b: Select best flavor with AI
        selected_flavor = select_kvm_flavor_with_ai(
            ai_client, requirements, available_flavors
        )
        
        if not selected_flavor:
            raise Exception("No suitable flavor selected")
        
        # Step 5c: Create KVM flavor reservation lease
        lease_name = f"{lease_name_base}-kvm"
        lease_id, lease_obj = create_kvm_lease_with_flavor(
            ai_client, requirements, selected_flavor.name, lease_name,
            duration_hours=args.lease_duration,
            start_delay_minutes=args.start_delay_minutes
        )
        
        # Step 5d: Launch KVM server using reserved flavor
        server_id, server_obj = launch_kvm_server_with_reserved_flavor(
            lease_obj, image_name, server_name, key_name=key_name
        )
        
        # Step 5e: Configure KVM server access (security groups, floating IP)
        floating_ip, sg_id = configure_kvm_server_access(server_obj, key_name=key_name)
        
        # Extract server info for snapshot and final output
        server_info = server_obj
        node_type = f"kvm_flavor_{selected_flavor.name}"
        provisioning_type = "kvm_chi"
        
        provision_snapshot = {
            "captured_at": datetime.utcnow().isoformat() + "Z",
            "provisioning_type": "kvm_chi",
            "site": args.site,
            "lease_id": lease_id,
            "server_id": server_id,
            "server_name": server_name,
            "selected_flavor": selected_flavor.name,
            "image_name": image_name,
            "floating_ip": floating_ip,
            "status": "ACTIVE"
        }
        
        print(f"\n✓ KVM provisioning successful via python-chi")
        
    except Exception as kvm_error:
        print(f"\n✗ KVM provisioning failed: {str(kvm_error)}")
        raise Exception(f"KVM provisioning failure: {str(kvm_error)}")

else:
    # ===== BARE METAL PROVISIONING PATH (CHI@TACC, etc.) =====
    print(f"\n{'='*60}")
    print(f"Bare Metal Provisioning Flow")
    print(f"{'='*60}")
    print(f"✓ Site: {args.site} (Bare Metal)")
    
    try:
        # Step 5: Create lease with fallback chain
        if available_resources and available_resources.get('node_types'):
            lease_id, reservation_id, node_type = attempt_lease_with_fallbacks(
                ai_client, requirements, available_resources, lease_name_base,
                duration_hours=args.lease_duration,
                start_delay_minutes=args.start_delay_minutes
            )
            print(f"\n✓ Final node type: {node_type}")
        else:
            # No discovery data, single attempt with specified node_type
            print(f"\n✓ Target node type: {node_type}")
            lease_name = f"{lease_name_base}-{node_type}"
            lease_id, reservation_id = create_lease_with_ai(
                ai_client, requirements, node_type, lease_name,
                duration_hours=args.lease_duration,
                filter_expression=filter_expression,
                start_delay_minutes=args.start_delay_minutes
            )
        
        # Step 6: Launch bare-metal server with reservation
        server_id, server_info = launch_server_with_sdk(
            os_conn, server_name, image_id, key_name, network_id, reservation_id
        )
        
        # Step 7: Assign floating IP
        if not args.no_floating_ip:
            floating_ip = assign_floating_ip(os_conn, server_id)
        
        provision_snapshot = build_provision_snapshot(
            os_conn,
            server_info,
            server_id,
            server_name,
            image_name,
            image_id,
            node_type,
            reservation_id=reservation_id,
            lease_id=lease_id,
            resource_properties=(filter_expression or json.dumps(["=", "$node_type", node_type]))
        )
        
        provisioning_type = "bare_metal"
        print(f"\n✓ Bare metal provisioning successful")
        
    except Exception as baremetal_error:
        print(f"\n✗ Bare metal provisioning failed: {str(baremetal_error)}")
        raise Exception(f"Bare metal provisioning failure: {str(baremetal_error)}")
```

### 4. provision_v2.py - Update Final Summary Section

Replace references to `is_kvm_fallback` with `provisioning_type`:

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

## Implementation Order

1. Clean up the corrupted provision_v2.py file (restore from git or manually remove duplicate code)
2. Add python-chi imports at top
3. Add five new KVM functions 
4. Replace provisioning logic in main() with site-aware branching
5. Update final summary to use provisioning_type
6. Test syntax with pylance
7. Test on KVM@TACC with `--site kvm` parameter

## Testing

```bash
python provision_v2.py --repo https://github.com/yrcong/RelTR --site KVM@TACC --lease-duration 24
```

Expected output:
- ✓ Site detected: KVM@TACC (KVM)
- ✓ KVM Flavor Discovery
- ✓ AI selected flavor
- ✓ Lease created with flavor reservation
- ✓ KVM server is ACTIVE
- ✓ Security group assigned
- ✓ Floating IP associated
- ✓ KVM provisioning successful via python-chi

## Notes

- KVM is now a **first-class provisioning path** (not a fallback)
- Site detection is automatic via `--site` parameter
- If `--site` contains "kvm", uses python-chi workflow
- Otherwise uses existing bare-metal Blazar workflow
- Both paths include proper error handling and logging
- Both paths save provision_snapshot for inspection
