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
from config import load_config
from ai_client import AIClient
from repo_analyzer import RepoAnalyzer
from image_selector import ImageSelector


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
                     if img.name.startswith('CC-') and img.status == 'active']
        
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
            # Just pick the first candidate for simplicity
            # (could enhance with another AI call for details)
            selected_image = candidates[0]
            print(f"\n✓ Final Selection: {selected_image}")
            
            # Get image ID
            for img in cc_images:
                if img.name == selected_image:
                    return selected_image, img.id
        
        # Fallback
        return "CC-Ubuntu22.04", cc_images[0].id
        
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


def create_lease_with_ai(ai_client: AIClient, requirements: dict, 
                         node_type: str, lease_name: str):
    """Create Blazar lease with AI-determined duration."""
    print(f"\n{'='*60}")
    print("Step 5: Create Hardware Reservation")
    print(f"{'='*60}")
    
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
    start_time = current_time + timedelta(minutes=2)
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
        lease = blazar.lease.create(
            name=lease_name,
            start=start_str,
            end=end_str,
            reservations=[{
                "resource_type": "physical:host",
                "min": 1,
                "max": 1,
                "resource_properties": f'["=", "$node_type", "{node_type}"]',
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
        
        # Attach to server
        server = os_conn.compute.get_server(server_id)
        os_conn.compute.add_floating_ip_to_server(
            server, available_ip.floating_ip_address
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
    parser.add_argument('--site', default='uc', help='Chameleon site (default: uc)')
    parser.add_argument('--network', default='sharednet1', help='Network name')
    parser.add_argument('--no-floating-ip', action='store_true', help='Skip floating IP')
    parser.add_argument('--skip-repo-clone', action='store_true', help='Skip repo clone (testing)')
    
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
        
        # Determine node type
        node_type = args.node_type
        if not node_type:
            # Simple heuristic
            if requirements.get('gpu_required'):
                node_type = "gpu_rtx_6000"
            else:
                node_type = "compute_cascadelake_r640"
        
        print(f"\n✓ Target node type: {node_type}")
        
        # Step 5: Create lease
        lease_name = args.lease_name or f"auto-{node_type}-{datetime.now().strftime('%Y%m%d%H%M')}"
        lease_id, reservation_id = create_lease_with_ai(
            ai_client, requirements, node_type, lease_name
        )
        
        # Step 6: Launch server
        server_name = args.server_name or f"auto-server-{datetime.now().strftime('%Y%m%d%H%M')}"
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

