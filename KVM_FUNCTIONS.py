"""
KVM Provisioning Functions for provision_v2.py

Add these functions to provision_v2.py after the _first_value() function
and before _find_baremetal_node()
"""

def discover_kvm_flavors_with_chi(ai_client: AIClient, requirements: dict, site: str = "KVM@TACC"):
    """
    Discover available GPU flavors at KVM site using python-chi.
    
    Returns:
        List of chi flavor objects, or empty list if chi unavailable
    """
    if not PYTHON_CHI_AVAILABLE:
        print(f"⚠ python-chi not available; skipping KVM flavor discovery")
        return []
    
    print(f"\n{'='*60}")
    print("KVM Flavor Discovery (via python-chi)")
    print(f"{'='*60}")
    
    try:
        # Set site context
        print(f"→ Setting site context: {site}")
        context.use_site(site)
        context.choose_project()
        print(f"✓ Site context established")
        
        # Discover flavors
        gpu_required = requirements.get('gpu_required', False)
        if gpu_required:
            print(f"→ Querying GPU-capable flavors...")
            flavors = chi_server.list_flavors(gpu=True, reservable=True)
            print(f"✓ Found {len(flavors)} GPU-capable reservable flavors")
        else:
            print(f"→ Querying all reservable flavors...")
            flavors = chi_server.list_flavors(reservable=True)
            print(f"✓ Found {len(flavors)} reservable flavors")
        
        if not flavors:
            print(f"⚠ No reservable flavors found at {site}")
            return []
        
        # Log available flavors
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
    """
    Use AI to select best flavor from available KVM flavors.
    
    Returns:
        Selected flavor object, or None if no suitable flavor found
    """
    if not available_flavors:
        print(f"⚠ No flavors available for selection")
        return None
    
    if len(available_flavors) == 1:
        print(f"✓ Only one flavor available, selecting: {available_flavors[0].name}")
        return available_flavors[0]
    
    # Build flavor details for AI
    flavor_list = "\n".join([
        f"- {f.name}: {getattr(f, 'vcpus', 'N/A')}vCPU, {getattr(f, 'ram', 'N/A')}MB RAM, {getattr(f, 'disk', 'N/A')}GB disk"
        for f in available_flavors
    ])
    
    system_prompt = """You are a resource manager selecting cloud VM flavors.
Choose the best flavor matching the requirements. Prefer smaller flavors for better availability while meeting CPU/RAM minimums.

Return JSON:
{
    "flavor_name": "name_of_selected_flavor",
    "reasoning": "explanation"
}"""
    
    user_prompt = f"""Requirements:
- CPU: {requirements.get('cpu_cores', 'N/A')} cores minimum
- RAM: {requirements.get('ram_gb', 'N/A')} GB minimum
- GPU: {'Required' if requirements.get('gpu_required') else 'Not required'}
- CUDA: {'Required' if requirements.get('cuda_required') else 'Not required'}

Available flavors:
{flavor_list}

Select the best matching flavor."""
    
    try:
        response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
        result = ai_client.parse_json_response(response)
        selected_name = result.get('flavor_name', '')
        
        # Find the flavor by name
        for flavor in available_flavors:
            if flavor.name == selected_name:
                print(f"✓ AI selected flavor: {selected_name}")
                print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
                return flavor
        
        # Fallback to first flavor if AI selection didn't match
        print(f"⚠ AI selection '{selected_name}' not found, using first flavor")
        return available_flavors[0]
    
    except Exception as e:
        print(f"⚠ AI flavor selection failed: {e}, using first flavor")
        return available_flavors[0]


def create_kvm_lease_with_flavor(ai_client: AIClient, requirements: dict, 
                                 flavor_name: str, lease_name: str,
                                 duration_hours: int = None, start_delay_minutes: int = 2):
    """
    Create KVM flavor-based Blazar lease via python-chi.
    
    Returns:
        (lease_id, lease_object)
    """
    if not PYTHON_CHI_AVAILABLE:
        raise Exception("python-chi required for KVM lease creation")
    
    print(f"\n{'='*60}")
    print("Step 5: Create KVM Flavor Reservation")
    print(f"{'='*60}")
    
    # Determine lease duration
    if duration_hours is not None:
        hours = duration_hours
        print(f"✓ Using manual duration: {hours} hours")
    else:
        try:
            current_time = datetime.now()
            system_prompt = """You are a cloud resource manager.
Determine appropriate lease duration for machine learning workloads on KVM.

Return JSON: {"duration_hours": <hours>, "reasoning": "explanation"}
Default to 24 hours if uncertain."""
            
            user_prompt = f"""Requirements: {json.dumps(requirements, indent=2, ensure_ascii=False)}
Determine lease duration in hours."""
            
            response = ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            result = ai_client.parse_json_response(response)
            hours = int(result.get('duration_hours', 24))
            print(f"✓ AI determined duration: {hours} hours")
            print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
        except Exception as e:
            print(f"⚠ AI duration failed: {e}, using default 24 hours")
            hours = 24
    
    try:
        # Create lease with flavor reservation
        print(f"\nCreating KVM flavor reservation lease:")
        print(f"  Name: {lease_name}")
        print(f"  Flavor: {flavor_name}")
        print(f"  Duration: {hours} hours")
        
        my_lease = chi_lease.Lease(lease_name, duration=timedelta(hours=hours))
        my_lease.add_flavor_reservation(name=flavor_name, amount=1)
        my_lease.submit(idempotent=True)
        
        lease_id = my_lease.id
        print(f"✓ Lease created: {lease_id}")
        print(f"✓ Lease status: {my_lease.status}")
        
        # Wait for lease to activate
        print(f"\nWaiting for lease to activate...")
        import time
        max_wait = 300  # 5 minutes
        start_wait = time.time()
        
        while time.time() - start_wait < max_wait:
            my_lease.refresh()
            status = my_lease.status
            
            if status == 'ACTIVE':
                print(f"✓ Lease is ACTIVE")
                
                # Verify reservation was created
                reserved = my_lease.get_reserved_flavors()
                if reserved:
                    print(f"✓ Reserved flavors confirmed: {len(reserved)} flavor(s)")
                    for rf in reserved:
                        print(f"    - {rf.name}")
                else:
                    raise Exception("Lease active but no reserved flavors found")
                
                return lease_id, my_lease
            
            elif status == 'ERROR':
                raise Exception(f"Lease entered ERROR state: {my_lease.error_message if hasattr(my_lease, 'error_message') else 'Unknown error'}")
            else:
                print(f"  Status: {status}, waiting...")
                time.sleep(10)
        
        raise Exception(f"Timeout waiting for KVM lease activation after {max_wait}s")
    
    except Exception as e:
        raise Exception(f"KVM lease creation failed: {str(e)}")


def launch_kvm_server_with_reserved_flavor(lease_obj, image_name: str, 
                                           server_name: str, key_name: str = None):
    """
    Launch KVM server using reserved flavor from lease.
    Sets up security groups and floating IP.
    
    Returns:
        (server_id, server_obj)
    """
    if not PYTHON_CHI_AVAILABLE:
        raise Exception("python-chi required for KVM server launch")
    
    print(f"\n{'='*60}")
    print("Step 6: Launch KVM Server")
    print(f"{'='*60}")
    
    try:
        # Get reserved flavor
        reserved = lease_obj.get_reserved_flavors()
        if not reserved:
            raise Exception("No reserved flavors found in active lease")
        
        reserved_flavor = reserved[0]
        print(f"→ Using reserved flavor: {reserved_flavor.name}")
        
        # Create server using chi.server.Server
        print(f"\nLaunching KVM server:")
        print(f"  Name: {server_name}")
        print(f"  Flavor: {reserved_flavor.name}")
        print(f"  Image: {image_name}")
        if key_name:
            print(f"  Keypair: {key_name}")
        
        my_server = chi_server.Server(
            name=server_name,
            flavor_name=reserved_flavor.name,
            image_name=image_name,
            key_name=key_name
        )
        my_server.submit()
        
        server_id = my_server.id
        print(f"✓ Server creation initiated: {server_id}")
        
        # Wait for server to become ACTIVE
        print(f"\nWaiting for KVM server to become ACTIVE...")
        print(f"(This typically takes 2-5 minutes for VMs)")
        
        import time
        max_wait = 600  # 10 minutes
        start_wait = time.time()
        last_status = None
        
        while time.time() - start_wait < max_wait:
            my_server.refresh()
            status = my_server.status
            
            if status != last_status:
                print(f"  Status: {status}")
                last_status = status
            
            if status == 'ACTIVE':
                print(f"✓ KVM server is ACTIVE")
                return server_id, my_server
            elif status == 'ERROR':
                fault_msg = getattr(my_server, 'fault', {})
                if isinstance(fault_msg, dict):
                    fault_msg = fault_msg.get('message', 'Unknown error')
                raise Exception(f"Server entered ERROR state: {fault_msg}")
            
            time.sleep(10)
        
        raise Exception(f"Timeout waiting for KVM server activation after {max_wait}s")
    
    except Exception as e:
        raise Exception(f"KVM server launch failed: {str(e)}")


def configure_kvm_server_access(server_obj, key_name: str = None):
    """
    Configure KVM server for SSH access and assign floating IP.
    
    Returns:
        (floating_ip, security_group_id)
    """
    if not PYTHON_CHI_AVAILABLE:
        print(f"⚠ python-chi not available; skipping KVM access configuration")
        return None, None
    
    print(f"\n{'='*60}")
    print("Step 7: Configure KVM Server Access")
    print(f"{'='*60}")
    
    try:
        # Assign or create SSH security group
        print(f"→ Configuring SSH security group...")
        existing_groups = chi_network.list_security_groups(name_filter="ssh")
        
        if existing_groups:
            sg = existing_groups[0]
            print(f"  Using existing SSH security group: {sg.name}")
        else:
            print(f"  Creating new SSH security group...")
            sg = chi_network.SecurityGroup({
                "name": "Allow SSH",
                "description": "Allow incoming SSH connections"
            })
            sg.add_rule("ingress", "tcp", 22)
            sg.submit()
            print(f"  ✓ Created security group: {sg.name}")
        
        # Add security group to server
        server_obj.add_security_group(sg.id)
        print(f"✓ Security group '{sg.name}' assigned to server")
        
        # Associate floating IP
        print(f"→ Associating floating IP...")
        fip = server_obj.associate_floating_ip()
        print(f"✓ Floating IP assigned: {fip}")
        
        return fip, sg.id
    
    except Exception as e:
        print(f"⚠ KVM access configuration warning: {e}")
        return None, None
