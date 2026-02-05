"""
Reservation Fallback Strategy Module

Implements intelligent fallback strategies for hardware provisioning:
1. Try primary node type with full duration
2. Fallback to alternative node types (shorter duration if needed)
3. Fallback to KVM-based VMs as last resort
4. Implement exponential backoff and retry logic
"""
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import blz


@dataclass
class FallbackOption:
    """Represents a single fallback reservation option."""
    node_type: Optional[str]  # None means KVM fallback
    duration_hours: int
    priority: int  # 1=highest priority (primary), 2=first fallback, etc.
    description: str
    is_kvm: bool = False


class ReservationFallbackManager:
    """Manages intelligent fallback for hardware reservations."""
    
    # Node type hierarchy by compute class
    COMPUTE_NODE_HIERARCHY = {
        'high_performance': ['compute_icelake_r750', 'compute_icelake_r650', 'compute_cascadelake_r', 'compute_cascadelake'],
        'general_purpose': ['compute_skylake', 'compute_cascadelake', 'compute_haswell_ib'],
        'arm64': ['compute_arm64'],
        'storage': ['storage', 'storage_hierarchy'],
    }
    
    GPU_NODE_HIERARCHY = {
        'high_end': ['gpu_a100_pcie', 'gpu_a100_sxm'],
        'mid_range': ['gpu_rtx_6000', 'gpu_p100_nvlink', 'gpu_p100_v100'],
        'budget': ['gpu_p100', 'gpu_k80', 'gpu_m40'],
    }
    
    def __init__(self, ai_client=None):
        """Initialize fallback manager."""
        self.ai_client = ai_client
        self.blazar = blz()
    
    def generate_fallback_chain(
        self,
        primary_node_type: str,
        requirements: Dict[str, Any],
        available_node_types: List[str],
        primary_duration_hours: int = 48,
        min_duration_hours: int = 2,
    ) -> List[FallbackOption]:
        """
        Generate a chain of fallback options, ordered by priority.
        
        Args:
            primary_node_type: The preferred node type
            requirements: Hardware requirements dict
            available_node_types: List of available node types from Blazar
            primary_duration_hours: Duration for primary option
            min_duration_hours: Minimum acceptable duration for fallbacks
        
        Returns:
            List of FallbackOption, ordered by priority (highest first)
        """
        fallback_chain = []
        priority = 1
        
        # Option 1: Primary node type with full duration
        fallback_chain.append(FallbackOption(
            node_type=primary_node_type,
            duration_hours=primary_duration_hours,
            priority=priority,
            description=f"Primary: {primary_node_type} for {primary_duration_hours}h"
        ))
        priority += 1
        
        # Option 2: Primary node type with reduced duration (if applicable)
        if primary_duration_hours > min_duration_hours and primary_duration_hours >= 6:
            reduced_duration = max(primary_duration_hours // 2, min_duration_hours)
            fallback_chain.append(FallbackOption(
                node_type=primary_node_type,
                duration_hours=reduced_duration,
                priority=priority,
                description=f"Fallback: {primary_node_type} for {reduced_duration}h (reduced duration)"
            ))
            priority += 1
        
        # Option 3-N: Alternative node types of same class
        if requirements.get('gpu_required'):
            alternatives = self._get_gpu_alternatives(
                primary_node_type, available_node_types, primary_duration_hours
            )
        else:
            alternatives = self._get_compute_alternatives(
                primary_node_type, available_node_types, primary_duration_hours
            )
        
        for alt_node_type, alt_duration, description in alternatives:
            fallback_chain.append(FallbackOption(
                node_type=alt_node_type,
                duration_hours=alt_duration,
                priority=priority,
                description=description
            ))
            priority += 1
        
        # Final fallback: KVM (VM-based)
        # KVM is more likely to have resources available
        fallback_chain.append(FallbackOption(
            node_type=None,
            duration_hours=primary_duration_hours,
            priority=priority,
            description="Fallback: KVM-based VM (when bare metal unavailable)",
            is_kvm=True
        ))
        priority += 1
        
        return fallback_chain
    
    def _get_compute_alternatives(
        self,
        primary_node_type: str,
        available_node_types: List[str],
        duration_hours: int,
    ) -> List[Tuple[str, int, str]]:
        """Get alternative compute node types, ordered by suitability."""
        alternatives = []
        used = {primary_node_type}
        
        # Find which class the primary belongs to
        primary_class = None
        for class_name, nodes in self.COMPUTE_NODE_HIERARCHY.items():
            if primary_node_type in nodes:
                primary_class = class_name
                break
        
        # If primary is general_purpose, try other general_purpose nodes
        # Otherwise try general_purpose nodes as fallback
        if primary_class == 'general_purpose':
            candidate_lists = [
                self.COMPUTE_NODE_HIERARCHY['general_purpose'],
                self.COMPUTE_NODE_HIERARCHY['high_performance'],
            ]
        elif primary_class == 'high_performance':
            candidate_lists = [
                self.COMPUTE_NODE_HIERARCHY['high_performance'],
                self.COMPUTE_NODE_HIERARCHY['general_purpose'],
            ]
        else:
            candidate_lists = [
                self.COMPUTE_NODE_HIERARCHY.get(primary_class, []),
                self.COMPUTE_NODE_HIERARCHY['general_purpose'],
                self.COMPUTE_NODE_HIERARCHY['high_performance'],
            ]
        
        # Flatten and deduplicate candidates
        candidates = []
        for candidate_list in candidate_lists:
            for node in candidate_list:
                if node not in used and node in available_node_types:
                    candidates.append(node)
                    used.add(node)
        
        # Add candidates with both full and reduced durations
        for i, node_type in enumerate(candidates):
            priority_offset = i * 2
            
            # Full duration version
            alternatives.append((
                node_type,
                duration_hours,
                f"Alt {priority_offset + 1}: {node_type} ({duration_hours}h)"
            ))
            
            # Reduced duration version (if worth trying)
            if duration_hours > 4:
                reduced = max(4, duration_hours // 2)
                alternatives.append((
                    node_type,
                    reduced,
                    f"Alt {priority_offset + 2}: {node_type} ({reduced}h, reduced)"
                ))
        
        return alternatives[:10]  # Limit to 10 alternatives to avoid explosion
    
    def _get_gpu_alternatives(
        self,
        primary_node_type: str,
        available_node_types: List[str],
        duration_hours: int,
    ) -> List[Tuple[str, int, str]]:
        """Get alternative GPU node types, ordered by suitability."""
        alternatives = []
        used = {primary_node_type}
        
        # Find which class the primary belongs to
        primary_class = None
        for class_name, nodes in self.GPU_NODE_HIERARCHY.items():
            if primary_node_type in nodes:
                primary_class = class_name
                break
        
        # Try same class first, then fallback to other classes
        if primary_class:
            candidate_lists = [
                self.GPU_NODE_HIERARCHY[primary_class],
                self.GPU_NODE_HIERARCHY['mid_range'],
                self.GPU_NODE_HIERARCHY['high_end'],
                self.GPU_NODE_HIERARCHY['budget'],
            ]
        else:
            candidate_lists = list(self.GPU_NODE_HIERARCHY.values())
        
        # Flatten candidates
        candidates = []
        for candidate_list in candidate_lists:
            for node in candidate_list:
                if node not in used and node in available_node_types:
                    candidates.append(node)
                    used.add(node)
        
        # Add candidates with reduced durations
        for i, node_type in enumerate(candidates[:8]):  # Limit GPU options
            priority_offset = i * 2
            
            alternatives.append((
                node_type,
                duration_hours,
                f"GPU Alt {priority_offset + 1}: {node_type} ({duration_hours}h)"
            ))
            
            if duration_hours > 4:
                reduced = max(4, duration_hours // 2)
                alternatives.append((
                    node_type,
                    reduced,
                    f"GPU Alt {priority_offset + 2}: {node_type} ({reduced}h)"
                ))
        
        return alternatives
    
    def try_create_lease(
        self,
        lease_name: str,
        node_type: Optional[str],
        duration_hours: int,
        start_delay_minutes: int = 2,
        project_id: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> Tuple[bool, Optional[str], Optional[str], str]:
        """
        Attempt to create a lease with a specific node type.
        
        Returns:
            (success: bool, lease_id: Optional[str], reservation_id: Optional[str], message: str)
        """
        try:
            now = datetime.utcnow()
            start_time = now + timedelta(minutes=start_delay_minutes)
            end_time = start_time + timedelta(hours=duration_hours)
            
            start_str = start_time.strftime("%Y-%m-%d %H:%M")
            end_str = end_time.strftime("%Y-%m-%d %H:%M")
            
            # Build resource properties
            if node_type:
                resource_props = json.dumps(["=", "$node_type", node_type])
                resource_type = "physical:host"
            else:
                # For KVM fallback, still use physical:host but with different properties
                # Actually, KVM doesn't use Blazar, we'll handle it separately
                raise ValueError("KVM fallback not yet implemented in this function")
            
            # Create lease
            lease = self.blazar.lease.create(
                name=lease_name,
                start=start_str,
                end=end_str,
                reservations=[{
                    "resource_type": resource_type,
                    "min": 1,
                    "max": 1,
                    "hypervisor_properties": "",
                    "resource_properties": resource_props,
                }],
                events=[]
            )
            
            lease_id = lease['id']
            
            # Wait for lease to become ACTIVE
            print(f"    Waiting for lease activation (timeout: {timeout_seconds}s)...")
            start_wait = time.time()
            max_wait = timeout_seconds
            
            while time.time() - start_wait < max_wait:
                lease_info = self.blazar.lease.get(lease_id)
                status = lease_info.get('status', '')
                
                if status == 'ACTIVE':
                    reservations = lease_info.get('reservations', [])
                    if reservations:
                        reservation_id = reservations[0].get('id', '')
                        msg = f"✓ Lease created and ACTIVE (ID: {lease_id})"
                        return True, lease_id, reservation_id, msg
                    else:
                        return False, lease_id, None, "No reservations in lease"
                elif status == 'ERROR':
                    return False, lease_id, None, "Lease entered ERROR state"
                
                time.sleep(3)
            
            # One last status check before failing
            lease_info = self.blazar.lease.get(lease_id)
            status = lease_info.get('status', '')
            if status == 'ACTIVE':
                reservations = lease_info.get('reservations', [])
                if reservations:
                    reservation_id = reservations[0].get('id', '')
                    msg = f"✓ Lease created and ACTIVE after timeout (ID: {lease_id})"
                    return True, lease_id, reservation_id, msg
            return False, lease_id, None, f"Timeout waiting for activation after {timeout_seconds}s (status: {status})"
        
        except Exception as e:
            error_msg = str(e)
            return False, None, None, error_msg
    
    def attempt_reservations(
        self,
        lease_basename: str,
        fallback_chain: List[FallbackOption],
        start_delay_minutes: int = 2,
        max_attempts: Optional[int] = None,
    ) -> Tuple[bool, Optional[str], Optional[str], str, FallbackOption]:
        """
        Attempt reservations following the fallback chain.
        
        Args:
            lease_basename: Base name for lease (e.g., 'auto-compute-')
            fallback_chain: Ordered list of FallbackOption
            start_delay_minutes: Delay before lease start
            max_attempts: Max attempts (None = try all)
        
        Returns:
            (success, lease_id, reservation_id, message, successful_option)
        """
        print(f"\n{'='*60}")
        print("Attempting Hardware Reservation (with fallbacks)")
        print(f"{'='*60}")
        print(f"Fallback chain ({len(fallback_chain)} options):")
        for i, opt in enumerate(fallback_chain, 1):
            print(f"  {i}. {opt.description}")
        
        attempts = 0
        max_attempts = max_attempts or len(fallback_chain)
        
        for fallback_opt in fallback_chain[:max_attempts]:
            attempts += 1
            print(f"\n[Attempt {attempts}/{max_attempts}] {fallback_opt.description}")
            
            if fallback_opt.is_kvm:
                print("    ⚠ KVM fallback (VM-based) - skipping Blazar, will use OpenStack directly")
                return True, "kvm-lease", None, "Using KVM fallback (no Blazar lease)", fallback_opt
            
            # Build unique lease name with timestamp and option ID
            ts = datetime.now().strftime('%Y%m%d%H%M%S')
            lease_name = f"{lease_basename}-{fallback_opt.node_type}-{ts}-opt{attempts}"
            
            success, lease_id, reservation_id, message = self.try_create_lease(
                lease_name,
                fallback_opt.node_type,
                fallback_opt.duration_hours,
                start_delay_minutes=start_delay_minutes,
                timeout_seconds=300,
            )
            
            if success:
                print(f"    {message}")
                return True, lease_id, reservation_id, message, fallback_opt
            else:
                print(f"    ✗ Failed: {message}")
                # Small delay between attempts
                if attempts < max_attempts:
                    print("    Waiting 5s before next attempt...")
                    time.sleep(5)
        
        error_msg = "All reservation attempts failed"
        return False, None, None, error_msg, None


def format_fallback_report(
    success: bool,
    fallback_chain: List[FallbackOption],
    successful_option: Optional[FallbackOption],
    message: str,
) -> str:
    """Generate a human-readable report of fallback attempts."""
    report = []
    report.append(f"\n{'='*60}")
    report.append("Reservation Fallback Report")
    report.append(f"{'='*60}")
    report.append(f"Status: {'✓ SUCCESS' if success else '✗ FAILED'}")
    report.append(f"Message: {message}")
    
    if successful_option:
        report.append(f"\nSuccessful option:")
        report.append(f"  {successful_option.description}")
        report.append(f"  Node type: {successful_option.node_type or 'KVM (VM-based)'}")
        report.append(f"  Duration: {successful_option.duration_hours}h")
    
    report.append(f"\nFallback chain had {len(fallback_chain)} options")
    
    return "\n".join(report)
