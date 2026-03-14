"""
KVM Fallback Launcher Module

Handles VM-based provisioning when bare metal is unavailable.
Uses OpenStack Nova directly (no Blazar reservations needed).
"""
from typing import Dict, Optional, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import conn


def select_kvm_flavor(
    os_conn,
    cpu_cores: int = 2,
    ram_gb: int = 2,
    min_disk_gb: int = 1,
) -> str:
    """
    Select appropriate KVM flavor based on requirements.
    
    Returns:
        Flavor ID or name
    """
    print(f"\n  Selecting KVM flavor (CPU: {cpu_cores}, RAM: {ram_gb}GB)...")
    
    try:
        # Normalize missing requirements
        if ram_gb is None:
            print("  ⚠ RAM requirement missing; defaulting to 2 GB for flavor selection")
            ram_gb = 2
        if cpu_cores is None:
            print("  ⚠ CPU requirement missing; defaulting to 2 cores for flavor selection")
            cpu_cores = 2

        flavors = list(os_conn.compute.flavors())

        # Exclude baremetal flavor for KVM
        flavors = [f for f in flavors if f.name != "baremetal"]

        # Prefer non-GPU flavors for KVM fallback to improve availability
        non_gpu_flavors = [f for f in flavors if "gpu" not in f.name.lower() and "h100" not in f.name.lower()]
        if non_gpu_flavors:
            flavors = non_gpu_flavors

        if not flavors:
            raise Exception("No KVM-capable flavors available (only baremetal found)")

        # Filter suitable flavors
        suitable = []
        for flavor in flavors:
            if (flavor.vcpus >= cpu_cores and 
            flavor.ram >= (ram_gb * 1024) and  # RAM in MB
            getattr(flavor, "disk", 0) >= min_disk_gb):
                suitable.append(flavor)

        if not suitable:
            print("  ⚠ No flavor found matching requirements, using smallest KVM flavor with sufficient disk")
            suitable = flavors
            # Ensure disk is sufficient for the image
            suitable = [f for f in suitable if getattr(f, "disk", 0) >= min_disk_gb] or suitable

        # Sort by vcpu then RAM to get the smallest suitable
        suitable.sort(key=lambda f: (f.vcpus, f.ram))
        selected = suitable[0]

        print(f"  ✓ Selected flavor: {selected.name}")
        print(f"    CPU: {selected.vcpus}, RAM: {selected.ram}MB")

        return selected.id

    except Exception as e:
        raise Exception(f"KVM flavor selection failed: {e}")


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
    Launch a KVM-based VM instance.
    
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
