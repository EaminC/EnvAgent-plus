#!/usr/bin/env python3
"""
Automated Hardware Provisioning Tool v2.0

This tool integrates with the existing EnvAgent-plus API core tools
and uses the OpenStack SDK via envboot.osutil for better performance.

Features:
- Intelligent fallback strategy for resource availability
- Multiple node type options
- Reduced duration fallbacks
- KVM (VM-based) fallback option

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
from typing import List, Tuple, Optional, Dict, Any

# Import existing infrastructure
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import conn, blz

# Import new 2.0 modules
from config import load_config
from ai_client import AIClient
from repo_analyzer import RepoAnalyzer
from image_selector import ImageSelector
from resource_discovery import ResourceDiscovery
from reservation_fallback import ReservationFallbackManager, format_fallback_report
from kvm_launcher import launch_kvm_instance, get_kvm_connection_info


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


def determine_lease_duration_with_ai(
    ai_client: AIClient,
    requirements: dict,
    default_hours: int = 48,
) -> int:
    """Use AI to determine appropriate lease duration."""
    current_time = datetime.now()
    
    system_prompt = """You are a cloud resource manager.
Determine appropriate lease duration based on requirements.

Return JSON:
{
    "duration_hours": <integer hours>,
    "reasoning": "explanation"
}

For small workloads, suggest 24-48 hours.
For complex setups, suggest 48-72 hours.
Default to 48 hours if uncertain."""
    
    user_prompt = f"""Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}

Requirements:
{json.dumps(requirements, indent=2, ensure_ascii=False)}

Determine appropriate lease duration in hours."""
    
    try:
        response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
        result = ai_client.parse_json_response(response)
        hours = int(result.get('duration_hours', default_hours))
        print(f"✓ AI determined duration: {hours} hours")
        print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
        return hours
    except Exception as e:
        print(f"⚠ AI duration failed, using default {default_hours} hours: {e}")
        return default_hours


def create_lease_with_fallbacks(
    ai_client: AIClient,
    requirements: dict,
    primary_node_type: str,
    available_node_types: List[str],
    lease_basename: str,
    duration_hours: int = None,
    start_delay_minutes: int = 2,
) -> Tuple[str, str, str]:
    """
    Create lease with intelligent fallback strategy.
    
    Returns:
        (lease_id, reservation_id, used_node_type)
    """
    print(f"\n{'='*60}")
    print("Step 5: Create Hardware Reservation (with Fallbacks)")
    print(f"{'='*60}")
    
    # Determine duration
    if duration_hours is None:
        duration_hours = determine_lease_duration_with_ai(ai_client, requirements)
    else:
        print(f"✓ Using manual duration: {duration_hours} hours")
    
    # Initialize fallback manager
    fallback_mgr = ReservationFallbackManager(ai_client)
    
    # Generate fallback chain
    fallback_chain = fallback_mgr.generate_fallback_chain(
        primary_node_type=primary_node_type,
        requirements=requirements,
        available_node_types=available_node_types,
        primary_duration_hours=duration_hours,
        min_duration_hours=2,
    )
    
    # Attempt reservations
    success, lease_id, reservation_id, message, successful_option = \
        fallback_mgr.attempt_reservations(
            lease_basename=lease_basename,
            fallback_chain=fallback_chain,
            start_delay_minutes=start_delay_minutes,
            max_attempts=None,  # Try full chain to allow KVM fallback
        )
    
    # Print report
    print(format_fallback_report(success, fallback_chain, successful_option, message))
    
    if not success:
        raise Exception(f"All reservation attempts failed: {message}")
    
    # Handle KVM fallback case
    if successful_option and successful_option.is_kvm:
        print("\n⚠ Using KVM (VM-based) instead of bare metal")
        print("   This is a temporary fallback - consider retrying later for bare metal")
        return lease_id, reservation_id, "kvm"
    
    used_node_type = successful_option.node_type if successful_option else primary_node_type
    print(f"\n✓ Reservation successful: {used_node_type}")
    return lease_id, reservation_id, used_node_type


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
        
        if not node_type:
            # Initialize ResourceDiscovery
            resource_discovery = ResourceDiscovery(ai_client, default_site=args.site)
            
            # Discover available resources
            print(f"\n{'='*60}")
            print("Discovering Available Resources")
            print(f"{'='*60}")
            available_resources = resource_discovery.discover_resources(args.site)
            
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
                    # Fallback: pick from available node types
                    if requirements.get('gpu_required'):
                        # Try to find a GPU node type
                        gpu_types = [nt for nt in available_resources['node_types'] if 'gpu' in nt.lower()]
                        node_type = gpu_types[0] if gpu_types else list(available_resources['node_types'])[0]
                    else:
                        # Pick first compute node type
                        compute_types = [nt for nt in available_resources['node_types'] if 'compute' in nt.lower()]
                        node_type = compute_types[0] if compute_types else list(available_resources['node_types'])[0]
                    print(f"✓ Fallback node type: {node_type}")
            else:
                # No discovery data, use hard-coded fallback
                print("⚠ Resource discovery returned no data, using fallback")
                if requirements.get('gpu_required'):
                    node_type = "gpu_rtx_6000"
                else:
                    node_type = "compute_cascadelake_r640"
        
        print(f"\n✓ Target node type: {node_type}")
        
        # Step 5: Create lease with fallback strategy
        lease_basename = args.lease_name or f"auto-{node_type}"
        available_node_types = available_resources.get('node_types', [node_type]) if available_resources else [node_type]
        
        lease_id, reservation_id, used_node_type = create_lease_with_fallbacks(
            ai_client=ai_client,
            requirements=requirements,
            primary_node_type=node_type,
            available_node_types=available_node_types,
            lease_basename=lease_basename,
            duration_hours=args.lease_duration,
            start_delay_minutes=args.start_delay_minutes
        )
        
        # Step 6: Launch server
        server_name = args.server_name or f"auto-server-{datetime.now().strftime('%Y%m%d%H%M')}"
        
        # Handle KVM fallback differently
        if used_node_type == "kvm":
            print(f"\n{'='*60}")
            print("Step 6: Launch KVM-based VM")
            print(f"{'='*60}")
            print("⚠ KVM fallback mode: launching VM instead of bare metal")
            print("   (Reservation ID not applicable for KVM)")
            reservation_id = None  # KVM doesn't use Blazar reservations
            
            # Launch KVM instance
            server_id, server_info = launch_kvm_instance(
                os_conn=os_conn,
                server_name=server_name,
                image_id=image_id,
                key_name=key_name,
                network_id=network_id,
                cpu_cores=requirements.get('cpu_cores', 2),
                ram_gb=requirements.get('ram_gb', 2),
            )
        else:
            print(f"\n{'='*60}")
            print("Step 6: Launch Bare Metal Server")
            print(f"{'='*60}")
            server_id, server_info = launch_server_with_sdk(
                os_conn, server_name, image_id, key_name, network_id, reservation_id
            )

        
        # Step 7: Floating IP
        floating_ip = None
        if not args.no_floating_ip:
            floating_ip = assign_floating_ip(os_conn, server_id)
        
        # Final summary
        print(f"\n{'='*60}")
        print("✓ Provisioning Complete!")
        print(f"{'='*60}")
        print(f"Server Name: {server_name}")
        print(f"Server ID: {server_id}")
        print(f"Lease ID: {lease_id}")
        if reservation_id:
            print(f"Reservation ID: {reservation_id}")
        print(f"Image: {image_name}")
        print(f"Node Type (requested): {node_type}")
        print(f"Node Type (actual): {used_node_type}")
        
        if used_node_type == "kvm":
            print(f"⚠ Running on KVM VM (bare metal unavailable)")

        
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
        with open(output_file, 'w') as f:
            json.dump({
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
            }, f, indent=2)
        
        print(f"\n✓ Info saved to: {output_file}")
        
    except KeyboardInterrupt:
        print(f"\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

