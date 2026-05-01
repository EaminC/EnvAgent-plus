#!/usr/bin/env python3
"""
Automated Hardware Provisioning Tool v2.0

This tool integrates with the existing EnvAgent-plus API core tools
and uses the OpenStack SDK via envboot.osutil for better performance.

Usage:
    python provision_v2.py --repo <github_repo_url> [options]

Example:
    python provision_v2.py --repo https://github.com/user/project
"""
import argparse
import sys
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime, timedelta

# Import existing infrastructure
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import conn, blz

# Import new 2.0 modules

# Import python-chi for KVM provisioning
try:
    from chi import context, lease as chi_lease, server as chi_server, network as chi_network
    PYTHON_CHI_AVAILABLE = True
except ImportError:
    PYTHON_CHI_AVAILABLE = False
    print("⚠ WARNING: python-chi not available; KVM provisioning will be limited")
from config import load_config
from ai_client import AIClient
from repo_analyzer import RepoAnalyzer
from image_selector import ImageSelector
from resource_discovery import ResourceDiscovery
from kvm_launcher import select_kvm_flavor, launch_kvm_instance, launch_kvm_instance_with_requirements, get_kvm_connection_info


def check_openstack_credentials():
    """Check if OpenStack credentials are set."""
    required_vars = ['OS_AUTH_URL', 'OS_USERNAME', 'OS_PROJECT_ID']
    missing = [var for var in required_vars if not os.environ.get(var)]
    
    if missing:
        print(f"\n{'='*60}")
        print("ERROR: Missing OpenStack Credentials")
        print(f"{'='*60}")
        print(f"Missing environment variables: {', '.join(missing)}")
        print("\nPlease run:")
        print(f"  source /path/to/your/openrc.sh")
        print()
        return False
    
    return True


def analyze_repository(ai_client: AIClient, repo_url: str, skip_clone: bool = False):
    """Analyze GitHub repository and determine requirements."""
    print(f"\n{'='*60}")
    print("Step 1: Repository Analysis")
    print(f"{'='*60}")
    
    analyzer = RepoAnalyzer(ai_client)
    
    if not skip_clone:
        repo_path = analyzer.clone_repo(repo_url)
    else:
        print("⚠ Skipping repository clone (test mode)")
        repo_path = Path("/tmp/test-repo")
        repo_path.mkdir(exist_ok=True)
    
    requirements = analyzer.analyze_requirements(repo_path)
    return requirements


def select_image_with_sdk(ai_client: AIClient, requirements: dict):
    """Select appropriate OS image using OpenStack SDK and AI."""
    print(f"\n{'='*60}")
    print("Step 2: Image Selection")
    print(f"{'='*60}")
    
    try:
        os_conn = conn()
        images = list(os_conn.compute.images())
        
        # Filter active CC images
        cc_images = [img for img in images 
                     if img.name.startswith('CC-') and img.status == 'ACTIVE']
        
        if not cc_images:
            raise Exception("No CC-* images found")
        
        print(f"✓ Found {len(cc_images)} available CC-* images")
        
        # Build image list for AI
        image_list = "\n".join([f"- {img.name} (ID: {img.id})" for img in cc_images])
        
        # AI selection (stage 1: narrow down)
        system_prompt = """You are a system administrator.
Select 3-5 candidate images from the list that match the requirements.

Image naming conventions:
- CC-Ubuntu20.04: Ubuntu 20.04 base
- CC-Ubuntu22.04: Ubuntu 22.04 base
- CC-Ubuntu24.04: Ubuntu 24.04 base
- CC-Ubuntu*-CUDA: Images with CUDA support
- CC-CentOS*: CentOS images

Return JSON:
{
    "candidates": ["image1", "image2", ...],
    "reasoning": "explanation"
}"""
        
        user_prompt = f"""Requirements:
- OS Type: {requirements.get('os_type', 'ubuntu')}
- OS Version: {requirements.get('os_version', '22.04')}
- CUDA Required: {requirements.get('cuda_required', False)}
- GPU Required: {requirements.get('gpu_required', False)}

Available images:
{image_list}

Select 3-5 best candidates."""
        
        response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
        result = ai_client.parse_json_response(response)
        candidates = result.get('candidates', [])
        
        print(f"✓ AI Stage 1: Selected {len(candidates)} candidates")
        print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
        
        # Stage 2: Get details and final selection
        if candidates:
            # Get detailed info for candidates
            candidate_details = []
            for candidate_name in candidates:
                # Normalize AI-returned names that may include " (ID: ...)" suffixes
                candidate_clean = candidate_name.split(" (ID:")[0].strip()
                for img in cc_images:
                    if img.name == candidate_clean:
                        candidate_details.append({
                            "name": img.name,
                            "id": img.id,
                            "size": img.size,
                            "min_disk": img.min_disk,
                            "min_ram": img.min_ram,
                            "created_at": str(img.created_at)
                        })
                        break
            
            if candidate_details:
                # TODO: Could add AI Stage 2 here for detailed comparison
                # For now, pick the first valid candidate
                selected = candidate_details[0]
                print(f"\n✓ Final Selection: {selected['name']}")
                print(f"  Image ID: {selected['id']}")
                return selected['name'], selected['id']
        
        # Fallback: Find any Ubuntu 22.04 CUDA image
        print("⚠ No candidates found, using fallback selection")
        for img in cc_images:
            if 'Ubuntu22.04' in img.name and 'CUDA' in img.name:
                print(f"✓ Fallback image: {img.name}")
                return img.name, img.id
        
        # Last resort: any Ubuntu 22.04 image
        for img in cc_images:
            if 'Ubuntu22.04' in img.name:
                print(f"✓ Last resort fallback: {img.name}")
                return img.name, img.id
        
        # If nothing works, fail clearly
        raise Exception("No suitable CC-* image found. Please check available images.")
        
    except Exception as e:
        print(f"✗ Image selection failed: {e}")
        raise


def ensure_keypair(os_conn, key_name: str, create_new: bool = False, 
                    public_key_path: str = None):
    """Ensure SSH keypair exists using OpenStack SDK."""
    print(f"\n{'='*60}")
    print("Step 3: SSH Key Management")
    print(f"{'='*60}")
    
    # Check if keypair exists
    try:
        kp = os_conn.compute.find_keypair(key_name)
        if kp:
            print(f"✓ Keypair exists: {key_name}")
            return key_name
    except Exception:
        pass
    
    # Create new keypair
    if create_new:
        kp = os_conn.compute.create_keypair(name=key_name)
        private_key_path = f"{key_name}.pem"
        with open(private_key_path, 'w') as f:
            f.write(kp.private_key)
        os.chmod(private_key_path, 0o600)
        print(f"✓ Created new keypair: {key_name}")
        print(f"✓ Private key saved to: {private_key_path}")
        return key_name
    
    # Import from public key file
    if public_key_path:
        pub_key_path = Path(public_key_path).expanduser()
        if pub_key_path.exists():
            with open(pub_key_path, 'r') as f:
                public_key = f.read()
            kp = os_conn.compute.create_keypair(name=key_name, public_key=public_key)
            print(f"✓ Imported keypair from: {public_key_path}")
            return key_name
    
    raise Exception(f"Keypair {key_name} not found. Use --create-key or --key-path")


def get_network_id(os_conn, network_name: str = "sharednet1"):
    """Get network ID using OpenStack SDK."""
    print(f"\n{'='*60}")
    print("Step 4: Network Configuration")
    print(f"{'='*60}")
    
    network = os_conn.network.find_network(network_name)
    if not network:
        raise Exception(f"Network {network_name} not found")
    
    print(f"✓ Found network: {network_name} (ID: {network.id})")
    return network.id


def attempt_lease_with_fallbacks(ai_client: AIClient, requirements: dict,
                                  available_resources: dict, lease_name_base: str,
                                  duration_hours: int = None, start_delay_minutes: int = 2):
    """Try lease creation with fallback chain through ranked node types."""
    
    print(f"\n{'='*60}")
    print("Step 5: Create Hardware Reservation (with fallbacks)")
    print(f"{'='*60}")
    
    ranked_types = available_resources.get('node_types', [])
    node_type_stats = available_resources.get('node_type_stats', {})
    
    if not ranked_types:
        raise Exception("No node types available for fallback")
    
    # Filter types based on requirements
    gpu_required = requirements.get('gpu_required', False)
    
    if gpu_required:
        # Try GPU types first, then fallback to compute/KVM for CPU-runnable workloads
        gpu_types = [nt for nt in ranked_types if 'gpu' in nt.lower()]
        compute_types = [nt for nt in ranked_types if 'compute' in nt.lower()]
        kvm_types = [nt for nt in ranked_types if 'kvm' in nt.lower() or 'vm' in nt.lower()]
        
        # Build tiered fallback: GPU → compute → KVM
        candidate_types = gpu_types + compute_types + kvm_types
        
        print(f"\n→ GPU required: Tiered fallback strategy:")
        print(f"   Tier 1 (GPU): {len(gpu_types)} types")
        print(f"   Tier 2 (Compute): {len(compute_types)} types")
        print(f"   Tier 3 (KVM/VM): {len(kvm_types)} types")
        print(f"   Total: {len(candidate_types)} attempts")
    else:
        # Try compute types first, then KVM, skip storage
        compute_types = [nt for nt in ranked_types if 'compute' in nt.lower()]
        kvm_types = [nt for nt in ranked_types if 'kvm' in nt.lower() or 'vm' in nt.lower()]
        other_types = [nt for nt in ranked_types 
                       if 'compute' not in nt.lower() 
                       and 'kvm' not in nt.lower() 
                       and 'vm' not in nt.lower()
                       and 'storage' not in nt.lower()]
        candidate_types = compute_types + kvm_types + other_types
        print(f"\n→ Trying {len(candidate_types)} node types (compute → KVM → others)")
    
    if not candidate_types:
        print("⚠ No matching types found, trying all ranked types")
        candidate_types = ranked_types
    
    # Try each candidate type
    last_error = None
    current_tier = None
    
    for idx, node_type in enumerate(candidate_types, 1):
        # Determine tier for progress display
        if gpu_required:
            if 'gpu' in node_type.lower():
                tier = "GPU (Tier 1)"
            elif 'compute' in node_type.lower():
                tier = "Compute (Tier 2 - degraded)"
            elif 'kvm' in node_type.lower() or 'vm' in node_type.lower():
                tier = "KVM/VM (Tier 3 - CPU fallback)"
            else:
                tier = "Other"
            
            # Show tier transition
            if tier != current_tier:
                if current_tier is not None:
                    print(f"\n→ Switching to: {tier}")
                current_tier = tier
        
        stats = node_type_stats.get(node_type, {})
        reservable = stats.get('reservable', 0)
        total = stats.get('total', 0)
        
        tier_label = f" [{tier}]" if gpu_required else ""
        print(f"\n[{idx}/{len(candidate_types)}] Attempting: {node_type}{tier_label} ({reservable} reservable / {total} total)")
        
        lease_name = f"{lease_name_base}-{node_type}"
        
        try:
            lease_id, reservation_id = create_lease_with_ai(
                ai_client, requirements, node_type, lease_name,
                duration_hours=duration_hours,
                filter_expression=None,
                start_delay_minutes=start_delay_minutes
            )
            print(f"✓ SUCCESS: Lease created with {node_type}")
            return lease_id, reservation_id, node_type
        
        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            
            # Show concise error
            if "Not enough resources" in error_msg:
                print(f"  ✗ No capacity available for {node_type}")
            elif "ERROR state" in error_msg:
                print(f"  ✗ Lease entered ERROR state for {node_type}")
            else:
                print(f"  ✗ Failed: {error_msg[:100]}")
            
            # Continue to next type
            if idx < len(candidate_types):
                print(f"  → Trying next option...")
                import time
                time.sleep(2)  # Brief pause between attempts
            continue
    
    # All Blazar bare-metal attempts failed
    print(f"\n✗ All {len(candidate_types)} Blazar fallback options exhausted")
    print(f"\n→ Attempting Tier 4: KVM VM (Direct Nova)")
    raise Exception(f"All Blazar fallback attempts failed. Last error: {last_error}")


def create_lease_with_ai(ai_client: AIClient, requirements: dict,
                         node_type: str, lease_name: str, duration_hours: int = None,
                         filter_expression: str = None, start_delay_minutes: int = 2):
    """Create Blazar lease with AI-determined duration (single attempt)."""
    import json  # For JSON encoding resource_properties
    
    # AI determines duration
    current_time = datetime.now()
    
    system_prompt = """You are a cloud resource manager.
Determine appropriate lease duration based on requirements.

Return JSON:
{
    "duration_hours": <hours>,
    "reasoning": "explanation"
}

Default to 24 hours if uncertain."""
    
    user_prompt = f"""Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}

Requirements:
{json.dumps(requirements, indent=2, ensure_ascii=False)}

Determine lease duration in hours."""
    
    # Use manual duration if provided, otherwise use AI
    if duration_hours is not None:
        hours = duration_hours
        print(f"✓ Using manual duration: {hours} hours")
    else:
        try:
            response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            result = ai_client.parse_json_response(response)
            hours = int(result.get('duration_hours', 24))
            print(f"✓ AI determined duration: {hours} hours")
            print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
        except Exception as e:
            print(f"⚠ AI duration failed, using default 24 hours: {e}")
            hours = 24
    
    # Calculate times
    start_time = current_time + timedelta(minutes=start_delay_minutes)
    end_time = start_time + timedelta(hours=hours)
    
    start_str = start_time.strftime("%Y-%m-%d %H:%M")
    end_str = end_time.strftime("%Y-%m-%d %H:%M")
    
    print(f"\nCreating lease:")
    print(f"  Name: {lease_name}")
    print(f"  Node Type: {node_type}")
    print(f"  Start: {start_str}")
    print(f"  End: {end_str}")
    
    # Create lease using Blazar client
    try:
        blazar = blz()
        # Use provided filter_expression or build default
        if filter_expression:
            resource_props = filter_expression
        else:
            # Format resource_properties as JSON string for Blazar API
            resource_props = json.dumps(["=", "$node_type", node_type])
        
        lease = blazar.lease.create(
            name=lease_name,
            start=start_str,
            end=end_str,
            reservations=[{
                "resource_type": "physical:host",
                "min": 1,
                "max": 1,
                "hypervisor_properties": "",
                "resource_properties": resource_props,
            }],
            events=[]
        )
        
        lease_id = lease['id']
        print(f"\n✓ Lease created: {lease_id}")
        
        # Wait for lease to become ACTIVE
        print("\nWaiting for lease to activate...")
        import time
        max_wait = 300  # 5 minutes
        start_wait = time.time()
        
        while time.time() - start_wait < max_wait:
            lease_info = blazar.lease.get(lease_id)
            status = lease_info.get('status', '')
            
            if status == 'ACTIVE':
                print("✓ Lease is ACTIVE")
                
                # Extract reservation ID
                reservations = lease_info.get('reservations', [])
                if reservations:
                    reservation_id = reservations[0].get('id', '')
                    print(f"✓ Reservation ID: {reservation_id}")
                    return lease_id, reservation_id
                else:
                    raise Exception("No reservations found in lease")
            elif status == 'ERROR':
                raise Exception("Lease entered ERROR state")
            else:
                print(f"  Status: {status}, waiting...")
                time.sleep(10)
        
        raise Exception("Timeout waiting for lease activation")
        
    except Exception as e:
        raise Exception(f"Lease creation failed: {str(e)}")


def launch_server_with_sdk(os_conn, server_name: str, image_id: str, 
                           key_name: str, network_id: str, reservation_id: str):
    """Launch server using OpenStack SDK."""
    print(f"\n{'='*60}")
    print("Step 6: Launch Bare Metal Server")
    print(f"{'='*60}")
    
    print(f"\nLaunching server:")
    print(f"  Name: {server_name}")
    print(f"  Image ID: {image_id}")
    print(f"  Key: {key_name}")
    print(f"  Network ID: {network_id}")
    print(f"  Reservation ID: {reservation_id}")
    
    try:
        server = os_conn.compute.create_server(
            name=server_name,
            image_id=image_id,
            flavor_id=os_conn.compute.find_flavor("baremetal").id,
            networks=[{"uuid": network_id}],
            key_name=key_name,
            scheduler_hints={"reservation": reservation_id}
        )
        
        server_id = server.id
        print(f"\n✓ Server creation initiated: {server_id}")
        
        # Wait for server to become ACTIVE
        print("\nWaiting for server to become ACTIVE...")
        print("(This may take 10-30 minutes for bare metal)")
        
        import time
        max_wait = 1800  # 30 minutes
        start_wait = time.time()
        last_status = None
        
        while time.time() - start_wait < max_wait:
            server_info = os_conn.compute.get_server(server_id)
            status = server_info.status
            
            if status != last_status:
                print(f"  Status: {status}")
                last_status = status
            
            if status == 'ACTIVE':
                print("\n✓ Server is ACTIVE")
                print(f"SUCCESS: server ACTIVE | server_id={server_id} | flavor/node_type=baremetal | floating_ip=unknown")
                return server_id, server_info
            elif status == 'ERROR':
                raise Exception("Server entered ERROR state")
            
            time.sleep(30)
        
        raise Exception("Timeout waiting for server activation")
        
    except Exception as e:
        raise Exception(f"Server launch failed: {str(e)}")


def assign_floating_ip(os_conn, server_id: str):
    """Assign floating IP to server."""
    print(f"\n{'='*60}")
    print("Step 7: Assign Floating IP")
    print(f"{'='*60}")
    
    try:
        # Find or create floating IP
        floating_ips = list(os_conn.network.ips())
        available_ip = None
        
        for fip in floating_ips:
            if not fip.fixed_ip_address:  # Unattached
                available_ip = fip
                break
        
        if not available_ip:
            print("Creating new floating IP...")
            # Find external network
            external_nets = [net for net in os_conn.network.networks() 
                           if net.is_router_external]
            if external_nets:
                available_ip = os_conn.network.create_ip(
                    floating_network_id=external_nets[0].id
                )
            else:
                raise Exception("No external network found")
        
        print(f"✓ Using floating IP: {available_ip.floating_ip_address}")
        
        # Attach to server via Neutron port
        # Get server's port
        server = os_conn.compute.get_server(server_id)
        
        # Find the server's port
        ports = list(os_conn.network.ports(device_id=server_id))
        if not ports:
            raise Exception("No network port found for server")
        
        port = ports[0]
        
        # Update floating IP to point to this port
        os_conn.network.update_ip(
            available_ip,
            port_id=port.id
        )
        
        print(f"✓ Floating IP attached")
        return available_ip.floating_ip_address
        
    except Exception as e:
        print(f"⚠ Failed to assign floating IP: {e}")
        return None


def _safe_get(obj, key, default=None):
    """Safely get value from dict/object with fallback."""
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


def _print_hardware_validation_summary(launch_info: dict, requirements: dict):
    """Print clear summary of predicted vs actual hardware and match status."""
    print(f"\n{'='*70}")
    print("HARDWARE VALIDATION SUMMARY")
    print(f"{'='*70}")
    
    # Predicted
    pred_cpu = requirements.get('cpu_cores', _safe_get(launch_info, 'predicted_cpu'))
    pred_ram = requirements.get('ram_gb', _safe_get(launch_info, 'predicted_ram_gb'))
    pred_disk = requirements.get('disk_gb', _safe_get(launch_info, 'predicted_disk_gb'))
    pred_gpu = requirements.get('gpu_required', _safe_get(launch_info, 'predicted_gpu_required', False))
    
    # Actual
    actual_cpu = _safe_get(launch_info, 'actual_cpu', 'unknown')
    actual_ram = _safe_get(launch_info, 'actual_ram_gb', 'unknown')
    actual_disk = _safe_get(launch_info, 'actual_disk_gb', 'unknown')
    selected_flavor = _safe_get(launch_info, 'selected_flavor', 'unknown')
    hardware_match = _safe_get(launch_info, 'hardware_match', None)
    undersized_reasons = _safe_get(launch_info, 'undersized_reasons', [])
    gpu_warning = _safe_get(launch_info, 'gpu_warning', None)
    
    print(f"\n→ Predicted Requirements:")
    print(f"  CPU:      {pred_cpu} cores")
    print(f"  RAM:      {pred_ram} GB")
    print(f"  Disk:     {pred_disk} GB")
    print(f"  GPU:      {'Yes' if pred_gpu else 'No'}")
    
    print(f"\n→ Actual Provisioned (Flavor: {selected_flavor}):")
    if actual_cpu != 'unknown':
        print(f"  CPU:      {actual_cpu} cores")
    if actual_ram != 'unknown':
        print(f"  RAM:      {actual_ram} GB")
    if actual_disk != 'unknown':
        print(f"  Disk:     {actual_disk} GB")
    print(f"  GPU:      No (KVM@TACC not available)")
    
    print(f"\n→ Match Status:")
    if hardware_match is True:
        print(f"  ✓ MATCH: Selected flavor satisfies all predicted requirements")
    elif hardware_match is False:
        print(f"  ⚠ MISMATCH: VM provisioned but undersized for predicted workload")
        if undersized_reasons:
            print(f"  Reasons:")
            for reason in undersized_reasons:
                print(f"    - {reason}")
    else:
        print(f"  ? UNKNOWN: Hardware matching not evaluated (old logs or error)")
    
    if gpu_warning:
        print(f"\n⚠ {gpu_warning}")
    
    print(f"\n{'='*70}\n")


def _extract_and_save_hardware_info(launch_info: dict, requirements: dict, json_output: dict) -> dict:
    """Extract hardware info from launch_info and merge into JSON output."""
    if not launch_info:
        return json_output
    
    hardware_info = {
        'predicted_cpu': requirements.get('cpu_cores', _safe_get(launch_info, 'predicted_cpu')),
        'predicted_ram_gb': requirements.get('ram_gb', _safe_get(launch_info, 'predicted_ram_gb')),
        'predicted_disk_gb': requirements.get('disk_gb', _safe_get(launch_info, 'predicted_disk_gb')),
        'predicted_gpu_required': requirements.get('gpu_required', _safe_get(launch_info, 'predicted_gpu_required', False)),
        'selected_flavor': _safe_get(launch_info, 'selected_flavor'),
        'actual_cpu': _safe_get(launch_info, 'actual_cpu'),
        'actual_ram_gb': _safe_get(launch_info, 'actual_ram_gb'),
        'actual_disk_gb': _safe_get(launch_info, 'actual_disk_gb'),
        'hardware_match': _safe_get(launch_info, 'hardware_match'),
        'undersized_reasons': _safe_get(launch_info, 'undersized_reasons', []),
        'gpu_warning': _safe_get(launch_info, 'gpu_warning'),
    }
    
    # Merge into output
    json_output['hardware_validation'] = hardware_info
    return json_output
    if hasattr(resource, "to_dict"):
        try:
            return resource.to_dict()
        except Exception:
            pass

    data = {}
    for attr in dir(resource):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(resource, attr)
        except Exception:
            continue
        if callable(value):
            continue
        data[attr] = value
    return data


def _first_value(mapping, keys, default="unknown"):
    """Return the first non-empty value for a list of keys."""
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}, ()):
            return value
    return default


def discover_kvm_flavors_with_chi(ai_client: AIClient, requirements: dict, site: str = "KVM@TACC"):
    """Discover available GPU flavors at KVM site using python-chi. Returns list of chi flavor objects, or empty list if chi unavailable."""
    if not PYTHON_CHI_AVAILABLE:
        print("⚠ python-chi not available; skipping KVM flavor discovery")
        return []
    try:
        print(f"→ Setting site context: {site}")
        context.use_site(site)
        context.choose_project()
        gpu_required = requirements.get('gpu_required', False)
        if gpu_required:
            flavors = chi_server.list_flavors(gpu=True, reservable=True)
        else:
            flavors = chi_server.list_flavors(reservable=True)
        if not flavors:
            print(f"⚠ No reservable flavors found at {site}")
            return []
        for i, flavor in enumerate(flavors[:5]):
            vcpu = getattr(flavor, 'vcpus', 'N/A')
            ram = getattr(flavor, 'ram', 'N/A')
            disk = getattr(flavor, 'disk', 'N/A')
            print(f"  [{i+1}] {flavor.name}: {vcpu}vCPU, {ram}MB RAM, {disk}GB disk")
        if len(flavors) > 5:
            print(f"  ... and {len(flavors) - 5} more")
        return flavors
    except Exception as e:
        print(f"✗ KVM flavor discovery failed: {e}")
        return []


def select_kvm_flavor_with_ai(ai_client: AIClient, requirements: dict, available_flavors: list):
    """Use AI to select best flavor from available KVM flavors."""
    if not available_flavors:
        print("⚠ No flavors available for selection")
        return None
    if len(available_flavors) == 1:
        print(f"✓ Only one flavor available, selecting: {available_flavors[0].name}")
        return available_flavors[0]
    flavor_list = "\n".join([f"- {f.name}: {getattr(f, 'vcpus', 'N/A')}vCPU, {getattr(f, 'ram', 'N/A')}MB RAM, {getattr(f, 'disk', 'N/A')}GB disk" for f in available_flavors])
    system_prompt = """You are a resource manager selecting cloud VM flavors. Choose the best flavor matching the requirements. CRITICAL: Flavor disk must be >= required disk size.
Return JSON: {"flavor_name": "name_of_selected_flavor", "reasoning": "explanation"}"""
    disk_req = f"- Disk: {requirements.get('disk_gb', 'N/A')} GB minimum\n" if 'disk_gb' in requirements else ""
    user_prompt = f"""Requirements:\n- CPU: {requirements.get('cpu_cores', 'N/A')} cores minimum\n- RAM: {requirements.get('ram_gb', 'N/A')} GB minimum\n{disk_req}- GPU: {'Required' if requirements.get('gpu_required') else 'Not required'}\n\nAvailable flavors:\n{flavor_list}\n\nSelect the best matching flavor."""
    try:
        response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
        result = ai_client.parse_json_response(response)
        selected_name = result.get('flavor_name', '')
        for flavor in available_flavors:
            if flavor.name == selected_name:
                print(f"✓ AI selected flavor: {selected_name}")
                return flavor
        print(f"⚠ AI selection '{selected_name}' not found, using first flavor")
        return available_flavors[0]
    except Exception as e:
        print(f"⚠ AI flavor selection failed: {e}, using first flavor")
        return available_flavors[0]


def create_kvm_lease_with_flavor(ai_client: AIClient, requirements: dict, flavor_name: str, lease_name: str, duration_hours: int = None, start_delay_minutes: int = 2):
    """Create KVM flavor-based Blazar lease via python-chi. Returns (lease_id, lease_obj)."""
    if not PYTHON_CHI_AVAILABLE:
        raise Exception("python-chi required for KVM lease creation")
    if duration_hours is not None:
        hours = duration_hours
        print(f"✓ Using manual duration: {hours} hours")
    else:
        try:
            system_prompt = "You are a cloud resource manager. Determine appropriate lease duration for machine learning workloads on KVM. Return JSON: {\"duration_hours\": <hours>, \"reasoning\": \"explanation\"}."
            user_prompt = f"Requirements: {json.dumps(requirements, indent=2, ensure_ascii=False)}\\nDetermine lease duration in hours."
            response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            result = ai_client.parse_json_response(response)
            hours = int(result.get('duration_hours', 24))
            print(f"✓ AI determined duration: {hours} hours")
        except Exception:
            print("⚠ AI duration failed, using default 24 hours")
            hours = 24
    try:
        print(f"Creating KVM flavor reservation lease: {lease_name} (flavor={flavor_name}, hours={hours})")
        my_lease = chi_lease.Lease(lease_name, duration=timedelta(hours=hours))
        my_lease.add_flavor_reservation(name=flavor_name, amount=1)
        my_lease.submit(idempotent=True)
        lease_id = my_lease.id
        import time
        max_wait = 300
        start_wait = time.time()
        while time.time() - start_wait < max_wait:
            my_lease.refresh()
            status = getattr(my_lease, 'status', '')
            if status == 'ACTIVE':
                reserved = my_lease.get_reserved_flavors()
                if not reserved:
                    raise Exception("Lease active but no reserved flavors found")
                return lease_id, my_lease
            if status == 'ERROR':
                raise Exception("Lease entered ERROR state")
            time.sleep(5)
        raise Exception("Timeout waiting for KVM lease activation")
    except Exception as e:
        raise Exception(f"KVM lease creation failed: {e}")


def launch_kvm_server_with_reserved_flavor(lease_obj, image_name: str, server_name: str, key_name: str = None):
    """Launch KVM server using reserved flavor from lease. Returns (server_id, server_obj)."""
    if not PYTHON_CHI_AVAILABLE:
        raise Exception("python-chi required for KVM server launch")
    try:
        reserved = lease_obj.get_reserved_flavors()
        if not reserved:
            raise Exception("No reserved flavors found in lease")
        reserved_flavor = reserved[0]
        print(f"→ Using reserved flavor: {reserved_flavor.name}")
        my_server = chi_server.Server(name=server_name, flavor_name=reserved_flavor.name, image_name=image_name, key_name=key_name)
        # submit() in some chi versions may attempt notebook display; ignore display-related errors
        try:
            my_server.submit()
        except Exception as e:
            if 'show' in str(e).lower():
                print(f"⚠ Warning: chi.submit() raised display error (non-fatal): {e}")
            else:
                raise

        # retrieving id may also trigger display in some chi builds; guard it
        try:
            server_id = my_server.id
        except Exception as e:
            if 'show' in str(e).lower():
                print(f"⚠ Warning: chi.server.id access raised display error (non-fatal): {e}")
                server_id = getattr(my_server, 'id', None)
            else:
                raise
        print(f"✓ Server creation initiated: {server_id}")
        import time
        max_wait = 600
        start_wait = time.time()
        last_status = None
        while time.time() - start_wait < max_wait:
            try:
                my_server.refresh()
            except TypeError as te:
                if "show" in str(te).lower():
                    print(f"⚠ Display error from chi library (expected in CLI mode), continuing...")
                    time.sleep(5)
                    continue
                raise
            status = getattr(my_server, 'status', None)
            if status != last_status:
                print(f"  Status: {status}")
                last_status = status
            if status == 'ACTIVE':
                print("✓ KVM server is ACTIVE")
                print(f"SUCCESS: server ACTIVE | server_id={server_id} | flavor/node_type={getattr(reserved_flavor, 'name', 'unknown')} | floating_ip=unknown")
                return server_id, my_server
            if status == 'ERROR':
                fault = getattr(my_server, 'fault', {})
                raise Exception(f"Server entered ERROR state: {fault}")
            time.sleep(5)
        raise Exception("Timeout waiting for KVM server activation")
    except Exception as e:
        raise Exception(f"KVM server launch failed: {e}")


def configure_kvm_server_access(server_obj, key_name: str = None):
    """Configure KVM server for SSH access and assign floating IP. Returns (floating_ip, sg_id)."""
    if not PYTHON_CHI_AVAILABLE:
        print("⚠ python-chi not available; skipping KVM access configuration")
        return None, None

    fip = None
    sg_id = None

    # Defensive: any failure in post-provision access setup should not crash
    try:
        try:
            existing_groups = chi_network.list_security_groups(name_filter="ssh")
        except Exception as e:
            print(f"⚠ Warning: could not list security groups: {e}")
            existing_groups = []

        if existing_groups:
            try:
                sg = existing_groups[0]
                sg_id = getattr(sg, 'id', None)
                print(f"Using existing SSH group: {getattr(sg,'name', sg_id)}")
            except Exception as e:
                print(f"⚠ Warning: failed to inspect existing security group: {e}")
                sg = None
        else:
            sg = None

        if sg is None:
            try:
                sg = chi_network.SecurityGroup({"name": "Allow SSH", "description": "Allow incoming SSH connections"})
                sg.add_rule("ingress", "tcp", 22)
                # submit may internally attempt display in some chi versions; guard it
                try:
                    sg.submit()
                except Exception as e:
                    print(f"⚠ Warning: security group submit failed (non-fatal): {e}")
                sg_id = getattr(sg, 'id', None)
                print(f"Created SSH group: {getattr(sg,'name', sg_id)}")
            except Exception as e:
                print(f"⚠ Warning: failed to create SSH security group: {e}")
                sg = None

        if sg is not None and getattr(sg, 'id', None):
            try:
                server_obj.add_security_group(sg.id)
            except Exception as e:
                print(f"⚠ Warning: could not add security group to server (non-fatal): {e}")

        # Associate floating IP, but don't die if it fails
        try:
            fip = server_obj.associate_floating_ip()
            print(f"✓ Floating IP assigned: {fip}")
        except Exception as e:
            print(f"⚠ Warning: could not associate floating IP (non-fatal): {e}")

    except Exception as e:
        print(f"⚠ KVM access configuration encountered unexpected error (non-fatal): {e}")

    return fip, sg_id


def _resource_to_dict(resource):
    """Best-effort conversion of an OpenStack resource into a JSON-safe dict."""
    if resource is None:
        return {}
    if isinstance(resource, dict):
        return dict(resource)
    if hasattr(resource, "to_dict"):
        try:
            return resource.to_dict()
        except Exception:
            pass

    data = {}
    for attr in dir(resource):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(resource, attr)
        except Exception:
            continue
        if callable(value):
            continue
        data[attr] = value
    return data


def _find_baremetal_node(os_conn, server_id: str, server_host: str = None):
    """Try to locate the backing bare metal node for an active server."""
    baremetal = getattr(os_conn, "baremetal", None)
    if baremetal is None:
        return {}

    finder_names = ("get_node", "find_node")
    for method_name in finder_names:
        method = getattr(baremetal, method_name, None)
        if not callable(method):
            continue
        for candidate in (server_id, server_host):
            if not candidate:
                continue
            try:
                node = method(candidate)
                if node:
                    return _resource_to_dict(node)
            except Exception:
                continue

    list_method = getattr(baremetal, "nodes", None)
    if not callable(list_method):
        list_method = getattr(baremetal, "list_nodes", None)
    if callable(list_method):
        try:
            try:
                nodes = list_method(details=True)
            except TypeError:
                nodes = list_method()
        except Exception:
            nodes = []

        if nodes is None:
            nodes = []
        try:
            iterable = list(nodes)
        except TypeError:
            iterable = [nodes]

        for node in iterable:
            node_dict = _resource_to_dict(node)
            values = [
                str(node_dict.get("uuid", "")),
                str(node_dict.get("id", "")),
                str(node_dict.get("name", "")),
                str(node_dict.get("instance_uuid", "")),
            ]
            instance_info = node_dict.get("instance_info")
            if isinstance(instance_info, dict):
                values.append(str(instance_info.get("image_source", "")))
            if server_id in values or (server_host and server_host in values):
                return node_dict

    return {}


def build_provision_snapshot(os_conn, server_info, server_id: str, server_name: str,
                             image_name: str, image_id: str, node_type: str,
                             reservation_id: str = None, lease_id: str = None,
                             resource_properties: str = None):
    """Capture a durable snapshot of the active server and reservation state."""
    server_raw = _resource_to_dict(server_info)
    server_host = _first_value(server_raw, [
        "OS-EXT-SRV-ATTR:host",
        "os-extended-server-attributes:host",
        "host",
        "hypervisor_hostname",
        "OS-EXT-SRV-ATTR:hypervisor_hostname",
        "instance_name",
        "OS-EXT-SRV-ATTR:instance_name",
    ])

    flavor_details = {}
    flavor_value = server_raw.get("flavor")
    flavor_id = None
    if isinstance(flavor_value, dict):
        flavor_id = flavor_value.get("id") or flavor_value.get("uuid")
    elif flavor_value not in (None, ""):
        flavor_id = flavor_value

    if flavor_id:
        try:
            flavor = os_conn.compute.find_flavor(flavor_id)
            if flavor:
                flavor_details = _resource_to_dict(flavor)
        except Exception:
            flavor_details = {}

    lease_raw = {}
    reservation_raw = {}
    if lease_id:
        try:
            lease = blz().lease.get(lease_id)
            lease_raw = _resource_to_dict(lease)
            if reservation_id:
                reservations = lease_raw.get("reservations") or []
                if not isinstance(reservations, list):
                    reservations = [reservations]
                for reservation in reservations:
                    reservation_dict = _resource_to_dict(reservation)
                    candidate_ids = [
                        str(reservation_dict.get("id", "")),
                        str(reservation_dict.get("reservation_id", "")),
                        str(reservation_dict.get("reservation", "")),
                    ]
                    if reservation_id in candidate_ids:
                        reservation_raw = reservation_dict
                        break
        except Exception:
            lease_raw = {}
            reservation_raw = {}

    try:
        baremetal_node_raw = _find_baremetal_node(os_conn, server_id, server_host)
    except Exception:
        baremetal_node_raw = {}

    return {
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "provisioning_type": "kvm_vm" if node_type == "kvm_vm_fallback" else "bare_metal",
        "lease_id": lease_id or "",
        "reservation_id": reservation_id or "",
        "server_id": server_id,
        "server_name": server_name,
        "selected_node_type": node_type,
        "resource_properties": resource_properties or "unknown",
        "lease_raw": lease_raw,
        "reservation_raw": reservation_raw,
        "server_raw": server_raw,
        "server_attributes": {
            "host": server_host,
            "hypervisor_hostname": _first_value(server_raw, ["hypervisor_hostname", "OS-EXT-SRV-ATTR:hypervisor_hostname"]),
            "instance_name": _first_value(server_raw, ["instance_name", "OS-EXT-SRV-ATTR:instance_name"]),
        },
        "flavor_details": flavor_details,
        "baremetal_node_raw": baremetal_node_raw,
        "image_name": image_name,
        "image_id": image_id,
        "addresses": server_raw.get("addresses", {}),
        "summary": {
            "actual_host": server_host,
            "actual_flavor": _first_value(flavor_details, ["name", "original_name"]),
            "actual_flavor_id": _first_value(flavor_details, ["id", "uuid"]),
            "actual_vcpus": _first_value(flavor_details, ["vcpus"]),
            "actual_ram_mb": _first_value(flavor_details, ["ram"]),
            "actual_disk_gb": _first_value(flavor_details, ["disk"]),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description='Automated Hardware Provisioning Tool v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Required
    parser.add_argument('--repo', required=True, help='GitHub repository URL')
    
    # Optional
    parser.add_argument('--env-file', help='.env configuration file path')
    parser.add_argument('--create-key', action='store_true', help='Create new SSH keypair')
    parser.add_argument('--key-name', help='SSH keypair name')
    parser.add_argument('--key-path', help='SSH public key path')
    parser.add_argument('--lease-name', help='Lease name')
    parser.add_argument('--server-name', help='Server name')
    parser.add_argument('--node-type', help='Node type (e.g., gpu_rtx_6000)')
    parser.add_argument('--lease-duration', type=int, help='Lease duration in hours (overrides AI)')
    parser.add_argument('--site', default='uc', help='Chameleon site (default: uc)')
    parser.add_argument('--network', default='sharednet1', help='Network name')
    parser.add_argument('--no-floating-ip', action='store_true', help='Skip floating IP')
    parser.add_argument('--skip-repo-clone', action='store_true', help='Skip repo clone (testing)')
    parser.add_argument('--start-delay-minutes', type=int, default=2, help='Delay start time by N minutes (default: 2)')
    
    args = parser.parse_args()
    
    try:
        print(f"\n{'='*60}")
        print("Automated Hardware Provisioning Tool v2.0")
        print(f"{'='*60}")
        
        # Check credentials
        if not check_openstack_credentials():
            sys.exit(1)
        
        # Load configuration
        config = load_config(args.env_file)
        print(f"✓ Configuration loaded")
        
        # Initialize AI client
        ai_client = AIClient(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
            model=config.openai_model
        )
        print(f"✓ AI client initialized")
        
        # Get OpenStack connection
        os_conn = conn()
        print(f"✓ OpenStack connection established")
        
        # Step 1: Analyze repository
        requirements = analyze_repository(
            ai_client, args.repo, args.skip_repo_clone
        )
        
        # Step 2: Select image
        image_name, image_id = select_image_with_sdk(ai_client, requirements)
        
        # Step 3: Ensure keypair
        key_name = args.key_name or config.default_key_name
        ensure_keypair(
            os_conn, key_name, 
            create_new=args.create_key,
            public_key_path=args.key_path or config.default_key_path
        )
        
        # Step 4: Get network
        network_id = get_network_id(os_conn, args.network)
        
        # Determine node type using ResourceDiscovery
        node_type = args.node_type
        filter_expression = None
        available_resources = None
        
        if not node_type:
            # Initialize ResourceDiscovery
            resource_discovery = ResourceDiscovery(ai_client, default_site=args.site)
            
            # Discover available resources
            print(f"\n{'='*60}")
            print("Discovering Available Resources")
            print(f"{'='*60}")
            available_resources = resource_discovery.discover_resources(
                args.site, requirements=requirements
            )
            
            if available_resources and available_resources.get('node_types'):
                print(f"✓ Found {len(available_resources['node_types'])} node types available")
                
                # Use AI to select best node type from available options
                try:
                    selection = resource_discovery.select_resources_with_ai(
                        requirements, available_resources
                    )
                    node_type = selection.get('node_type')
                    filter_expression = selection.get('filter_expression')
                    print(f"✓ AI selected node type: {node_type}")
                    print(f"  Reasoning: {selection.get('reasoning', 'N/A')}")
                except Exception as e:
                    print(f"⚠ AI selection failed: {e}")
                    # Fallback: pick from available node types (ranked by availability & fit)
                    ranked_types = available_resources.get('node_types', [])
                    
                    if not ranked_types:
                        raise Exception("No ranked node types available after discovery")
                    
                    # Try to find type matching requirements
                    node_type = None
                    if requirements.get('gpu_required'):
                        # Find first GPU type in ranked list
                        for nt in ranked_types:
                            if nt and isinstance(nt, str) and 'gpu' in nt.lower():
                                node_type = nt
                                break
                    else:
                        # Find first compute type in ranked list
                        for nt in ranked_types:
                            if nt and isinstance(nt, str) and 'compute' in nt.lower():
                                node_type = nt
                                break
                    
                    # If no match found, use first ranked type
                    if not node_type:
                        node_type = ranked_types[0]
                    
                    print(f"✓ Fallback node type: {node_type}")
            else:
                # No discovery data, use hard-coded fallback
                print("⚠ Resource discovery returned no data, using fallback")
                if requirements.get('gpu_required'):
                    node_type = "gpu_rtx_6000"
                else:
                    node_type = "compute_cascadelake_r640"
        
        # Step 5: Create lease / provision depending on site (KVM@TACC -> python-chi flow)
        # Ensure unique names per run to avoid collisions
        import random as _rand
        unique_suffix = datetime.now().strftime('%Y%m%d%H%M%S') + '-' + format(_rand.getrandbits(24), '06x')
        lease_name_base = (args.lease_name or f"auto-{datetime.now().strftime('%Y%m%d%H%M')}") + f"-{unique_suffix}"
        server_name = (args.server_name or f"auto-server-{datetime.now().strftime('%Y%m%d%H%M')}") + f"-{unique_suffix}"

        # Initialize provisioning result variables
        lease_id = None
        reservation_id = None
        server_id = None
        server_info = None
        provision_snapshot = {}
        provisioning_type = None

        is_kvm_site = 'kvm' in (args.site or '').lower()

        if is_kvm_site and PYTHON_CHI_AVAILABLE:
            # Preferred KVM path: use python-chi flavor reservations + chi.server
            try:
                print(f"\n{'='*60}")
                print("KVM@ site detected — using python-chi flavor reservation flow")
                print(f"{'='*60}")

                flavors = discover_kvm_flavors_with_chi(ai_client, requirements, site=args.site)
                if not flavors:
                    raise Exception("No reservable flavors discovered via python-chi")

                # Enhance requirements with image disk size for flavor selection
                enhanced_requirements = dict(requirements)
                try:
                    image_obj = os_conn.compute.find_image(image_id)
                    if image_obj and hasattr(image_obj, 'size') and image_obj.size:
                        import math
                        image_disk_gb = math.ceil(image_obj.size / (1024**3))
                        enhanced_requirements['disk_gb'] = image_disk_gb
                        print(f"→ Image {image_name} requires ~{image_disk_gb}GB disk")
                except Exception as e:
                    print(f"⚠ Could not get image disk size: {e}")

                # Prefer smaller flavors first (more likely to have capacity)
                # Filter out flavors that are too small for the selected image
                image_disk_gb = enhanced_requirements.get('disk_gb')
                if image_disk_gb:
                    filtered = [f for f in flavors if (getattr(f, 'disk', 0) or 0) >= image_disk_gb]
                    if not filtered:
                        print(f"⚠ No flavors large enough for image (~{image_disk_gb}GB); keeping full list")
                        filtered = flavors
                    else:
                        removed = len(flavors) - len(filtered)
                        if removed:
                            print(f"→ Filtered out {removed} flavor(s) smaller than image ({image_disk_gb}GB)")
                    flavors = filtered

                ordered_flavors = sorted(
                    flavors,
                    key=lambda f: (
                        (getattr(f, 'disk', 0) or 0),
                        (getattr(f, 'vcpus', 0) or 0),
                        (getattr(f, 'ram', 0) or 0),
                    )
                )

                # Improved retry policy: increase attempts and use exponential backoff
                import random, time
                max_total_attempts = 6
                # Backoff schedule aligned to attempt index (1-based)
                backoff_schedule = [5, 10, 20, 30, 45, 60]
                total_attempts = 0
                success = False
                last_error = None

                # Keep trying until we exhaust global attempts. Shuffle/rotate flavors between rounds
                while total_attempts < max_total_attempts and not success:
                    # create a per-round flavor order that is not always the same
                    attempt_flavors = ordered_flavors.copy()
                    try:
                        random.shuffle(attempt_flavors)
                    except Exception:
                        # If shuffle fails for some reason, fall back to rotation
                        if attempt_flavors:
                            rot = total_attempts % len(attempt_flavors)
                            attempt_flavors = attempt_flavors[rot:] + attempt_flavors[:rot]

                    for flavor in attempt_flavors:
                        if total_attempts >= max_total_attempts or success:
                            break

                        total_attempts += 1
                        attempt_no = total_attempts
                        flavor_name = getattr(flavor, 'name', str(flavor))
                        print(f"\n→ Attempt #{attempt_no}: Trying KVM flavor: {flavor_name}")

                        try:
                            lease_name = f"{lease_name_base}-{flavor_name}"
                            print(f"  → Creating lease for flavor {flavor_name} (lease: {lease_name})")
                            lease_id, lease_obj = create_kvm_lease_with_flavor(
                                ai_client, requirements, flavor_name, lease_name,
                                duration_hours=args.lease_duration,
                                start_delay_minutes=args.start_delay_minutes
                            )

                            print(f"  → Launching server with reserved flavor: {flavor_name}")
                            server_id, server_obj = launch_kvm_server_with_reserved_flavor(
                                lease_obj, image_name, server_name, key_name=key_name
                            )

                            # Configure access (security group / floating IP)
                            floating_ip, sg_id = configure_kvm_server_access(server_obj, key_name=key_name)

                            # Success
                            node_type = flavor_name
                            server_info = server_obj
                            provisioning_type = 'kvm_chi'
                            provision_snapshot = {
                                'lease_id': lease_id,
                                'server_id': server_id,
                                'server_raw': _resource_to_dict(server_obj),
                                'floating_ip': floating_ip,
                                'selected_flavor': node_type
                            }

                            print(f"\n✓ KVM provisioning via python-chi complete: server={server_id} flavor={flavor_name}")
                            success = True
                            break

                        except Exception as e:
                            last_error = str(e)
                            # Log the failure reason clearly
                            print(f"  ✗ Attempt #{attempt_no} failed for flavor {flavor_name}: {e}")
                            if 'no valid host' in str(e).lower():
                                print(f"    → Reason: No valid host / capacity; will try other flavors or retry after backoff")
                            else:
                                print(f"    → Reason: {e}; will retry if attempts remain")

                            # Backoff based on attempt number (safe index into schedule)
                            try:
                                wait_secs = backoff_schedule[min(attempt_no - 1, len(backoff_schedule) - 1)]
                                print(f"    → Backing off for {wait_secs}s before next attempt")
                                time.sleep(wait_secs)
                            except Exception:
                                pass

                            # move on to next flavor/attempt
                            continue

                    # end for flavors

                # end while attempts

                if not success:
                    raise Exception(f"KVM python-chi provisioning failed after {total_attempts} attempts: {last_error}")
            except Exception as chi_err:
                print(f"\n⚠ python-chi KVM flow failed: {chi_err}")
                print("→ Falling back to Blazar/Nova fallback chain")
                # Fall through to traditional Blazar flow below by not returning

        # If not a KVM site or python-chi failed, use the existing Blazar + fallback logic
        # **For KVM@TACC, skip bare-metal Blazar entirely (wrong reservation model)**
        if provisioning_type is None and not is_kvm_site:
            # Try bare-metal with Blazar (including the existing fallback chain)
            try:
                if available_resources and available_resources.get('node_types'):
                    lease_id, reservation_id, node_type = attempt_lease_with_fallbacks(
                        ai_client, requirements, available_resources, lease_name_base,
                        duration_hours=args.lease_duration,
                        start_delay_minutes=args.start_delay_minutes
                    )
                    print(f"\n✓ Final node type: {node_type}")
                else:
                    print(f"\n✓ Target node type: {node_type}")
                    lease_name = f"{lease_name_base}-{node_type}"
                    lease_id, reservation_id = create_lease_with_ai(
                        ai_client, requirements, node_type, lease_name,
                        duration_hours=args.lease_duration,
                        filter_expression=filter_expression,
                        start_delay_minutes=args.start_delay_minutes
                    )

                # Launch bare-metal server with reservation
                server_id, server_info = launch_server_with_sdk(
                    os_conn, server_name, image_id, key_name, network_id, reservation_id
                )

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
                provisioning_type = 'bare_metal'

            except Exception as blazar_error:
                # All Blazar attempts failed - try Tier 4: KVM VMs via Nova (direct)
                print(f"\n{'='*60}")
                print("TIER 4 FALLBACK: KVM Virtual Machines (direct Nova)")
                print(f"{'='*60}")
                print(f"Blazar bare-metal exhausted: {str(blazar_error)[:200]}")
                print(f"\n→ Switching to direct Nova VM launch (no reservation needed)")

                try:
                    cpu_cores = requirements.get('cpu_cores', 4)
                    ram_gb = requirements.get('ram_gb', 16)
                    server_id, server_info = launch_kvm_instance(
                        os_conn, server_name, image_id, key_name, network_id,
                        cpu_cores=cpu_cores, ram_gb=ram_gb
                    )

                    node_type = "kvm_vm_fallback"
                    provisioning_type = 'kvm_vm_fallback'
                    provision_snapshot = build_provision_snapshot(
                        os_conn,
                        server_info,
                        server_id,
                        server_name,
                        image_name,
                        image_id,
                        node_type,
                        reservation_id=None,
                        lease_id=None,
                        resource_properties="unknown"
                    )
                    print(f"\n✓ KVM VM fallback successful")

                except Exception as kvm_error:
                    print(f"\n✗ KVM VM fallback also failed: {str(kvm_error)}")
                    print(f"\n✗ All provisioning tiers exhausted:")
                    print(f"   Tier 1-3 (Blazar bare-metal): {str(blazar_error)[:150]}")
                    print(f"   Tier 4 (KVM VMs): {str(kvm_error)[:150]}")
                    raise Exception(f"Complete provisioning failure across all tiers")
        
        # For KVM@TACC: if chi provisioning failed/unavailable, fall back directly to Nova (no Blazar)
        elif provisioning_type is None and is_kvm_site:
            print(f"\n{'='*60}")
            print("KVM@TACC: Skipping bare-metal Blazar (wrong model for KVM)")
            print("TIER 4 FALLBACK: Direct Nova KVM launch with requirements-based flavor selection")
            print(f"{'='*60}")
            
            try:
                predicted_cpu_cores = requirements.get('cpu_cores', 4)
                predicted_ram_gb = requirements.get('ram_gb', 16)
                predicted_disk_gb = requirements.get('disk_gb', 20)
                predicted_gpu_required = requirements.get('gpu_required', False)
                
                print(f"\nPredicted hardware requirements:")
                print(f"  CPU: {predicted_cpu_cores} cores")
                print(f"  RAM: {predicted_ram_gb} GB")
                print(f"  Disk: {predicted_disk_gb} GB")
                if predicted_gpu_required:
                    print(f"  GPU: Required")
                
                server_id, launch_info = launch_kvm_instance_with_requirements(
                    os_conn, server_name, image_id, key_name, network_id,
                    predicted_cpu_cores=predicted_cpu_cores,
                    predicted_ram_gb=predicted_ram_gb,
                    predicted_disk_gb=predicted_disk_gb,
                    predicted_gpu_required=predicted_gpu_required,
                )
                
                server_info = launch_info.get('server_info')
                hardware_match = launch_info.get('hardware_match', False)
                
                # Print hardware validation summary
                _print_hardware_validation_summary(launch_info, requirements)
                
                provisioning_type = 'kvm_vm'
                node_type = 'kvm_vm_direct'
                provision_snapshot = {
                    'server_id': server_id,
                    'server_raw': _resource_to_dict(server_info),
                    'floating_ip': None,
                    'hardware_match': hardware_match,
                    'selected_flavor': launch_info.get('selected_flavor'),
                    'predicted_cpu': launch_info.get('predicted_cpu'),
                    'predicted_ram_gb': launch_info.get('predicted_ram_gb'),
                    'predicted_disk_gb': launch_info.get('predicted_disk_gb'),
                    'predicted_gpu_required': launch_info.get('predicted_gpu_required'),
                    'actual_cpu': launch_info.get('actual_cpu'),
                    'actual_ram_gb': launch_info.get('actual_ram_gb'),
                    'actual_disk_gb': launch_info.get('actual_disk_gb'),
                    'undersized_reasons': launch_info.get('undersized_reasons', []),
                    'gpu_warning': launch_info.get('gpu_warning'),
                }
                
                print(f"\n✓ KVM VM direct launch successful")
                if not hardware_match:
                    print(f"⚠ WARNING: VM provisioned but hardware is undersized or incomplete")
                    for reason in launch_info.get('undersized_reasons', []):
                        print(f"   - {reason}")
                if launch_info.get('gpu_warning'):
                    print(f"  {launch_info['gpu_warning']}")
                    
            except Exception as kvm_error:
                print(f"\n✗ KVM VM direct launch failed: {str(kvm_error)}")
                raise Exception(f"KVM@TACC provisioning failed: {str(kvm_error)}")
        
        # Step 7: Floating IP (skip for kvm_chi as it's already assigned)
        floating_ip = None
        if not args.no_floating_ip and provisioning_type != 'kvm_chi':
            try:
                floating_ip = assign_floating_ip(os_conn, server_id)
            except Exception as _e:
                print(f"⚠ Warning: assigning floating IP failed (non-fatal): {_e}")
                floating_ip = None
        elif provisioning_type == 'kvm_chi':
            # floating_ip already assigned via configure_kvm_server_access, extract from provision_snapshot
            try:
                floating_ip = provision_snapshot.get('floating_ip')
            except Exception:
                floating_ip = None
        
        # Final summary
        print(f"\n{'='*60}")
        print("✓ Provisioning Complete!")
        print(f"{'='*60}")
        print(f"Provisioning Type: {provisioning_type or 'unknown'}")
        print(f"Server Name: {server_name}")
        print(f"Server ID: {server_id}")
        if lease_id:
            print(f"Lease ID: {lease_id}")
        if reservation_id:
            print(f"Reservation ID: {reservation_id}")
        print(f"Image: {image_name}")
        print(f"Node Type: {node_type}")
        
        if floating_ip:
            print(f"Floating IP: {floating_ip}")
            print(f"\nSSH Connection:")
            print(f"  ssh ubuntu@{floating_ip}")
        else:
            # Get fixed IP
            addresses = server_info.addresses
            for net, addrs in addresses.items():
                for addr in addrs:
                    if addr.get('OS-EXT-IPS:type') == 'fixed':
                        print(f"Fixed IP: {addr.get('addr')}")
        
        # Save info to file
        output_file = f"{server_name}_info.json"
        
        # Extract hardware matching info if available
        hardware_match = provision_snapshot.get('hardware_match', None)
        
        # Build hardware validation summary for JSON
        hardware_validation = {
            'predicted_cpu': provision_snapshot.get('predicted_cpu'),
            'predicted_ram_gb': provision_snapshot.get('predicted_ram_gb'),
            'predicted_disk_gb': provision_snapshot.get('predicted_disk_gb'),
            'predicted_gpu_required': provision_snapshot.get('predicted_gpu_required'),
            'selected_flavor': provision_snapshot.get('selected_flavor'),
            'actual_cpu': provision_snapshot.get('actual_cpu'),
            'actual_ram_gb': provision_snapshot.get('actual_ram_gb'),
            'actual_disk_gb': provision_snapshot.get('actual_disk_gb'),
            'actual_gpu_count': provision_snapshot.get('actual_gpu_count', 0),
            'hardware_match': hardware_match,
            'undersized_reasons': provision_snapshot.get('undersized_reasons', []),
            'gpu_warning': provision_snapshot.get('gpu_warning'),
        }
        
        with open(output_file, 'w') as f:
            json.dump({
                'provisioning_type': provisioning_type or ('bare_metal' if lease_id else 'unknown'),
                'server_name': server_name,
                'server_id': server_id,
                'lease_id': lease_id,
                'reservation_id': reservation_id,
                'floating_ip': floating_ip,
                'image_name': image_name,
                'image_id': image_id,
                'node_type': node_type,
                'key_name': key_name,
                'network_id': network_id,
                'hardware_match': hardware_match,
                'hardware_validation': hardware_validation,  # Top-level easy access
                'provision_snapshot': provision_snapshot,
            }, f, indent=2)
        
        # Also print hardware match status
        if hardware_match is not None:
            if hardware_match:
                print(f"✓ Hardware Match: Yes (provisioned VM meets all predicted requirements)")
            else:
                print(f"⚠ Hardware Match: No (provisioned VM is undersized)")
                undersized_reasons = provision_snapshot.get('undersized_reasons', [])
                for reason in undersized_reasons:
                    print(f"    {reason}")
        
        print(f"\n✓ Info saved to: {output_file}")
        
    except KeyboardInterrupt:
        print(f"\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ ERROR: {str(e)}")
        # Print last-known identifiers for easier debugging
        try:
            print(f"Final server_id: {server_id}")
        except Exception:
            print("Final server_id: unknown")
        try:
            # node_type typically holds the selected flavor or node type
            print(f"Final flavor/node_type: {node_type}")
        except Exception:
            print("Final flavor/node_type: unknown")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

