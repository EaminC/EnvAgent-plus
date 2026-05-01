"""
KVM Fallback Launcher Module

Handles VM-based provisioning when bare metal is unavailable.
Uses OpenStack Nova directly (no Blazar reservations needed).
"""
from typing import Dict, Optional, Any, Tuple
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import conn


# Known KVM flavor specifications at TACC
# These serve as fallback if OpenStack metadata is incomplete
KNOWN_KVM_FLAVORS = {
    'm1.small': {'vcpu': 1, 'ram_gb': 2, 'disk_gb': 20},
    'm1.medium': {'vcpu': 2, 'ram_gb': 4, 'disk_gb': 40},
    'm1.large': {'vcpu': 4, 'ram_gb': 8, 'disk_gb': 80},
    'm1.xlarge': {'vcpu': 8, 'ram_gb': 16, 'disk_gb': 160},
    'm1.xxlarge': {'vcpu': 16, 'ram_gb': 32, 'disk_gb': 320},
}


def _get_flavor_specs(flavor) -> Dict[str, Any]:
    """Extract hardware specs from OpenStack flavor object, with fallback to known specs."""
    specs = {
        'name': flavor.name,
        'vcpu': getattr(flavor, 'vcpus', None),
        'ram_gb': (getattr(flavor, 'ram', None) or 0) / 1024,  # Convert MB to GB
        'disk_gb': getattr(flavor, 'disk', None),
    }
    
    # Fill in missing values from known specs if available
    if flavor.name in KNOWN_KVM_FLAVORS:
        known = KNOWN_KVM_FLAVORS[flavor.name]
        if specs['vcpu'] is None:
            specs['vcpu'] = known['vcpu']
        if specs['disk_gb'] is None:
            specs['disk_gb'] = known['disk_gb']
    
    return specs


def select_kvm_flavor_with_requirements(
    os_conn,
    predicted_cpu_cores: int = 2,
    predicted_ram_gb: int = 2,
    predicted_disk_gb: int = 20,
    predicted_gpu_required: bool = False,
    image_size_bytes: int = 0,
) -> Tuple[str, Dict[str, Any]]:
    """
    Intelligently select KVM flavor matching predicted requirements.
    
    Returns:
        (flavor_id, selection_info_dict)
        where selection_info includes:
            - selected_flavor_name
            - actual_vcpu, actual_ram_gb, actual_disk_gb
            - hardware_match (bool: all requirements satisfied)
            - undersized_reasons (list of reasons if not matched)
            - gpu_warning (if GPU required but not available)
    """
    print(f"\n  → Selecting KVM flavor for predicted requirements:")
    if predicted_cpu_cores is None:
        predicted_cpu_cores = 2
    if predicted_ram_gb is None:
        predicted_ram_gb = 2
    if predicted_disk_gb is None:
        predicted_disk_gb = 1
    print(f"     CPU: {predicted_cpu_cores} cores, RAM: {predicted_ram_gb}GB, Disk: {predicted_disk_gb}GB")
    if predicted_gpu_required:
        print(f"     GPU: Required")
    
    selection_info = {
        'selected_flavor_name': None,
        'actual_vcpu': None,
        'actual_ram_gb': None,
        'actual_disk_gb': None,
        'actual_gpu_count': 0,
        'hardware_match': False,
        'undersized_reasons': [],
        'gpu_warning': None,
    }
    
    try:
        # GPU warning
        if predicted_gpu_required:
            gpu_warning = "⚠ GPU required but KVM@TACC does not provide GPU flavors. Workload may fail to run."
            print(f"     {gpu_warning}")
            selection_info['gpu_warning'] = gpu_warning
        
        # Get all KVM flavors
        all_flavors = list(os_conn.compute.flavors())
        
        # Exclude baremetal and GPU-capable flavors for KVM@TACC.
        # KVM provisioning should only choose CPU/RAM/disk shapes here.
        kvm_flavors = [
            f for f in all_flavors
            if f.name != "baremetal" and "gpu" not in f.name.lower() and "h100" not in f.name.lower()
        ]
        
        if not kvm_flavors:
            raise Exception("No KVM-capable flavors available (only baremetal found)")
        
        # Parse flavor specs
        flavor_specs = []
        for flavor in kvm_flavors:
            specs = _get_flavor_specs(flavor)
            flavor_specs.append((flavor, specs))
        
        # Image disk requirement
        image_disk_gb = 0
        if image_size_bytes > 0:
            import math
            image_disk_gb = math.ceil(image_size_bytes / (1024**3))
        
        min_disk_gb = max(predicted_disk_gb, image_disk_gb)
        print(f"     → Minimum disk required: {min_disk_gb}GB (predicted: {predicted_disk_gb}GB, image: {image_disk_gb}GB)")
        
        # Filter flavors that satisfy ALL requirements
        matching_flavors = []
        for flavor, specs in flavor_specs:
            vcpu = specs['vcpu']
            ram_gb = specs['ram_gb']
            disk_gb = specs['disk_gb']
            
            if (vcpu is not None and vcpu >= predicted_cpu_cores and
                ram_gb is not None and ram_gb >= predicted_ram_gb and
                disk_gb is not None and disk_gb >= min_disk_gb):
                matching_flavors.append((flavor, specs))
        
        # Sort by size (smallest first)
        matching_flavors.sort(key=lambda x: (x[1]['vcpu'], x[1]['ram_gb'], x[1]['disk_gb']))
        
        if matching_flavors:
            selected_flavor, selected_specs = matching_flavors[0]
            print(f"\n  ✓ Selected flavor: {selected_flavor.name} (best match)")
            print(f"     Actual: {selected_specs['vcpu']} vCPU, {selected_specs['ram_gb']:.1f}GB RAM, {selected_specs['disk_gb']}GB disk")
            
            selection_info['selected_flavor_name'] = selected_flavor.name
            selection_info['actual_vcpu'] = selected_specs['vcpu']
            selection_info['actual_ram_gb'] = selected_specs['ram_gb']
            selection_info['actual_disk_gb'] = selected_specs['disk_gb']
            selection_info['hardware_match'] = not predicted_gpu_required
            if predicted_gpu_required:
                selection_info['undersized_reasons'] = [
                    "GPU: Not available on KVM@TACC"
                ]
                print("     Undersized: GPU: Not available on KVM@TACC")
            
            return selected_flavor.id, selection_info
        
        # No perfect match found - use smallest available flavor and report why
        print(f"\n  ⚠ No KVM flavor perfectly matches requirements")
        print(f"     → Using smallest available flavor and marking as undersized")
        
        # Sort all flavors by size
        flavor_specs.sort(key=lambda x: (x[1]['vcpu'], x[1]['ram_gb'], x[1]['disk_gb']))
        
        # Find smallest flavor with sufficient disk for image
        suitable_disk = [(f, s) for f, s in flavor_specs 
                        if s['disk_gb'] is not None and s['disk_gb'] >= image_disk_gb]
        
        if suitable_disk:
            selected_flavor, selected_specs = suitable_disk[0]
        else:
            # Last resort: smallest flavor overall
            selected_flavor, selected_specs = flavor_specs[0]
        
        print(f"\n  Selected flavor: {selected_flavor.name} (fallback)")
        print(f"     Actual: {selected_specs['vcpu']} vCPU, {selected_specs['ram_gb']:.1f}GB RAM, {selected_specs['disk_gb']}GB disk")
        
        # Record why this is undersized
        undersized_reasons = []
        if selected_specs['vcpu'] is not None and selected_specs['vcpu'] < predicted_cpu_cores:
            undersized_reasons.append(f"CPU: {selected_specs['vcpu']} < {predicted_cpu_cores}")
        if selected_specs['ram_gb'] is not None and selected_specs['ram_gb'] < predicted_ram_gb:
            undersized_reasons.append(f"RAM: {selected_specs['ram_gb']:.1f}GB < {predicted_ram_gb}GB")
        if selected_specs['disk_gb'] is not None and selected_specs['disk_gb'] < min_disk_gb:
            undersized_reasons.append(f"Disk: {selected_specs['disk_gb']}GB < {min_disk_gb}GB")
        if predicted_gpu_required:
            undersized_reasons.append("GPU: Not available")
        
        print(f"     Undersized: {', '.join(undersized_reasons)}")
        
        selection_info['selected_flavor_name'] = selected_flavor.name
        selection_info['actual_vcpu'] = selected_specs['vcpu']
        selection_info['actual_ram_gb'] = selected_specs['ram_gb']
        selection_info['actual_disk_gb'] = selected_specs['disk_gb']
        selection_info['hardware_match'] = False
        selection_info['undersized_reasons'] = undersized_reasons
        
        return selected_flavor.id, selection_info
    
    except Exception as e:
        raise Exception(f"KVM flavor selection failed: {e}")


def select_kvm_flavor(
    os_conn,
    cpu_cores: int = 2,
    ram_gb: int = 2,
    min_disk_gb: int = 1,
) -> str:
    """
    Legacy flavor selection (for backward compatibility).
    Use select_kvm_flavor_with_requirements() for enhanced tracking.
    
    Returns:
        Flavor ID or name
    """
    _, info = select_kvm_flavor_with_requirements(
        os_conn,
        predicted_cpu_cores=cpu_cores,
        predicted_ram_gb=ram_gb,
        predicted_disk_gb=min_disk_gb,
        predicted_gpu_required=False,
        image_size_bytes=0,
    )
    # Find flavor by name to get ID
    flavors = list(os_conn.compute.flavors())
    for flavor in flavors:
        if flavor.name == info['selected_flavor_name']:
            return flavor.id
    raise Exception(f"Could not find selected flavor {info['selected_flavor_name']}")


def launch_kvm_instance_with_requirements(
    os_conn,
    server_name: str,
    image_id: str,
    key_name: str,
    network_id: str,
    predicted_cpu_cores: int = 2,
    predicted_ram_gb: int = 2,
    predicted_disk_gb: int = 20,
    predicted_gpu_required: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """
    Launch KVM VM with intelligent flavor selection based on predicted requirements.
    
    Returns:
        (server_id, launch_info_dict)
        where launch_info includes:
            - server_id
            - server_info
            - selected_flavor
            - hardware_match (bool)
            - predicted_* fields
            - actual_* fields
            - undersized_reasons
            - gpu_warning
    """
    print(f"\n  Launching KVM VM with requirements-based flavor selection:")
    print(f"    Name: {server_name}")
    print(f"    Image ID: {image_id}")
    print(f"    Key: {key_name}")
    print(f"    Network ID: {network_id}")
    
    try:
        if predicted_cpu_cores is None:
            predicted_cpu_cores = 2
        if predicted_ram_gb is None:
            predicted_ram_gb = 2
        if predicted_disk_gb is None:
            predicted_disk_gb = 1

        # Get image size for disk calculation
        image_size_bytes = 0
        try:
            image = os_conn.compute.get_image(image_id)
            image_size_bytes = getattr(image, "size", 0) or 0
        except Exception:
            pass
        
        # Select flavor based on predicted requirements
        flavor_id, selection_info = select_kvm_flavor_with_requirements(
            os_conn,
            predicted_cpu_cores=predicted_cpu_cores,
            predicted_ram_gb=predicted_ram_gb,
            predicted_disk_gb=predicted_disk_gb,
            predicted_gpu_required=predicted_gpu_required,
            image_size_bytes=image_size_bytes,
        )
        
        # Create server without scheduler hints (no reservation)
        server = os_conn.compute.create_server(
            name=server_name,
            image_id=image_id,
            flavor_id=flavor_id,
            networks=[{"uuid": network_id}],
            key_name=key_name,
            # No scheduler hints for KVM
        )
        
        server_id = server.id
        print(f"\n  ✓ KVM instance creation initiated: {server_id}")
        
        # Wait for server to become ACTIVE
        print("\n  Waiting for KVM instance to become ACTIVE...")
        print("  (This typically takes 1-5 minutes for VMs)")
        
        import time
        max_wait = 600  # 10 minutes for VMs
        start_wait = time.time()
        last_status = None
        
        while time.time() - start_wait < max_wait:
            server_info = os_conn.compute.get_server(server_id)
            status = server_info.status
            
            if status != last_status:
                print(f"    Status: {status}")
                last_status = status
            
            if status == 'ACTIVE':
                print("\n  ✓ KVM instance is ACTIVE")
                
                # Return comprehensive launch info
                launch_info = {
                    'server_id': server_id,
                    'server_info': server_info,
                    'selected_flavor': selection_info['selected_flavor_name'],
                    'hardware_match': selection_info['hardware_match'],
                    'predicted_cpu': predicted_cpu_cores,
                    'predicted_ram_gb': predicted_ram_gb,
                    'predicted_disk_gb': predicted_disk_gb,
                    'predicted_gpu_required': predicted_gpu_required,
                    'actual_cpu': selection_info['actual_vcpu'],
                    'actual_ram_gb': selection_info['actual_ram_gb'],
                    'actual_disk_gb': selection_info['actual_disk_gb'],
                    'actual_gpu_count': selection_info['actual_gpu_count'],
                    'undersized_reasons': selection_info['undersized_reasons'],
                    'gpu_warning': selection_info['gpu_warning'],
                }
                
                return server_id, launch_info
            elif status == 'ERROR':
                # Extract fault details from Nova
                fault_msg = "Unknown error"
                try:
                    if hasattr(server_info, 'fault'):
                        fault = server_info.fault
                        if isinstance(fault, dict):
                            fault_msg = fault.get('message', 'No message provided')
                            fault_code = fault.get('code', 'N/A')
                            print(f"\n  ✗ Nova Fault Code: {fault_code}")
                            print(f"  ✗ Nova Fault Message: {fault_msg}")
                except Exception as e:
                    print(f"  ⚠ Could not extract fault details: {e}")
                
                raise Exception(f"KVM instance entered ERROR state: {fault_msg}")
            
            time.sleep(10)
        
        raise Exception(f"Timeout waiting for KVM instance activation after {max_wait}s")
    
    except Exception as e:
        raise Exception(f"KVM instance launch failed: {str(e)}")


def launch_kvm_instance(
    os_conn,
    server_name: str,
    image_id: str,
    key_name: str,
    network_id: str,
    cpu_cores: int = 2,
    ram_gb: int = 2,
) -> tuple:
    """
    Legacy KVM launcher (backward compatible).
    For requirements-based selection, use launch_kvm_instance_with_requirements().
    
    Returns:
        (server_id, server_info)
    """
    print(f"\n  Launching KVM VM:")
    print(f"    Name: {server_name}")
    print(f"    Image ID: {image_id}")
    print(f"    Key: {key_name}")
    print(f"    Network ID: {network_id}")
    
    try:
        # Determine minimum disk size from image (GB)
        min_disk_gb = 1
        try:
            image = os_conn.compute.get_image(image_id)
            image_size_bytes = getattr(image, "size", 0) or 0
            image_size_gb = int((image_size_bytes + (1024**3 - 1)) // (1024**3))
            # Add 1GB buffer to avoid edge cases where image size ~= flavor disk
            min_disk_gb = max(min_disk_gb, image_size_gb + 1)
        except Exception:
            pass

        # Select flavor
        flavor_id = select_kvm_flavor(os_conn, cpu_cores, ram_gb, min_disk_gb=min_disk_gb)
        
        # Create server without scheduler hints (no reservation)
        server = os_conn.compute.create_server(
            name=server_name,
            image_id=image_id,
            flavor_id=flavor_id,
            networks=[{"uuid": network_id}],
            key_name=key_name,
            # No scheduler hints for KVM
        )
        
        server_id = server.id
        print(f"\n  ✓ KVM instance creation initiated: {server_id}")
        
        # Wait for server to become ACTIVE
        print("\n  Waiting for KVM instance to become ACTIVE...")
        print("  (This typically takes 1-5 minutes for VMs)")
        
        import time
        max_wait = 600  # 10 minutes for VMs
        start_wait = time.time()
        last_status = None
        
        while time.time() - start_wait < max_wait:
            server_info = os_conn.compute.get_server(server_id)
            status = server_info.status
            
            if status != last_status:
                print(f"    Status: {status}")
                last_status = status
            
            if status == 'ACTIVE':
                print("\n  ✓ KVM instance is ACTIVE")
                return server_id, server_info
            elif status == 'ERROR':
                # Extract fault details from Nova
                fault_msg = "Unknown error"
                try:
                    if hasattr(server_info, 'fault'):
                        fault = server_info.fault
                        if isinstance(fault, dict):
                            fault_msg = fault.get('message', 'No message provided')
                            fault_code = fault.get('code', 'N/A')
                            print(f"\n  ✗ Nova Fault Code: {fault_code}")
                            print(f"  ✗ Nova Fault Message: {fault_msg}")
                except Exception as e:
                    print(f"  ⚠ Could not extract fault details: {e}")
                
                raise Exception(f"KVM instance entered ERROR state: {fault_msg}")
            
            time.sleep(10)
        
        raise Exception(f"Timeout waiting for KVM instance activation after {max_wait}s")
    
    except Exception as e:
        raise Exception(f"KVM instance launch failed: {str(e)}")


def get_kvm_connection_info(server_info) -> Dict[str, Any]:
    """Extract connection information from KVM instance."""
    info = {}
    
    try:
        # Extract fixed IP
        addresses = server_info.addresses
        for net, addrs in addresses.items():
            for addr in addrs:
                addr_type = addr.get('OS-EXT-IPS:type', 'fixed')
                if addr_type == 'fixed':
                    info['fixed_ip'] = addr.get('addr')
                elif addr_type == 'floating':
                    info['floating_ip'] = addr.get('addr')
        
        # Status
        info['status'] = server_info.status
        info['hypervisor'] = getattr(server_info, 'hypervisor_hostname', 'N/A')
        
    except Exception as e:
        print(f"  ⚠ Could not extract connection info: {e}")
    
    return info
