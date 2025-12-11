"""
Resource Discovery Module
Responsible for discovering available hardware resources on Chameleon Cloud
"""
import subprocess
import json
import requests
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from ai_client import AIClient

# Import OpenStack utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import blz


class ResourceDiscovery:
    """Resource Discovery"""
    
    def __init__(self, ai_client: AIClient, default_site: str = "uc"):
        """Initialize resource discovery"""
        self.ai_client = ai_client
        self.default_site = default_site
        self.base_url = "https://api.chameleoncloud.org"
    
    def get_sites(self) -> List[Dict[str, Any]]:
        """获取所有站点"""
        try:
            response = requests.get(f"{self.base_url}/sites?pretty")
            response.raise_for_status()
            data = response.json()
            return data.get('items', [])
        except Exception as e:
            raise Exception(f"获取站点列表失败: {str(e)}")
    
    def get_clusters(self, site: str) -> List[Dict[str, Any]]:
        """获取指定站点的集群"""
        try:
            response = requests.get(f"{self.base_url}/sites/{site}/clusters?pretty")
            response.raise_for_status()
            data = response.json()
            return data.get('items', [])
        except Exception as e:
            raise Exception(f"获取集群列表失败: {str(e)}")
    
    def get_nodes(self, site: str, cluster: str = "chameleon") -> List[Dict[str, Any]]:
        """获取指定集群的节点"""
        try:
            response = requests.get(f"{self.base_url}/sites/{site}/clusters/{cluster}/nodes?pretty")
            response.raise_for_status()
            data = response.json()
            return data.get('items', [])
        except Exception as e:
            raise Exception(f"获取节点列表失败: {str(e)}")
    
    def get_node_details(self, site: str, cluster: str, node_uid: str) -> Dict[str, Any]:
        """获取节点详细信息"""
        try:
            response = requests.get(
                f"{self.base_url}/sites/{site}/clusters/{cluster}/nodes/{node_uid}?pretty"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"获取节点详情失败: {str(e)}")
    
    def list_reservation_hosts(self) -> List[Dict[str, Any]]:
        """List all reservable hosts using Blazar client"""
        try:
            blazar = blz()
            # Get all hosts from Blazar
            hosts_raw = blazar.host.list()
            # Convert to list of dicts, handling both dict and object types
            hosts = []
            for host in hosts_raw:
                if isinstance(host, dict):
                    hosts.append(host)
                else:
                    # If it's an object, convert attributes to dict
                    host_dict = {}
                    for attr in dir(host):
                        if not attr.startswith('_'):
                            try:
                                val = getattr(host, attr)
                                if not callable(val):
                                    host_dict[attr] = val
                            except:
                                pass
                    hosts.append(host_dict)
            return hosts
        except Exception as e:
            raise Exception(f"Failed to list reservation hosts: {str(e)}")
    
    def get_host_details(self, host_id: str) -> Dict[str, Any]:
        """获取主机详细信息"""
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'host', 'show', host_id, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取主机详情失败: {e.stderr}")
    
    def check_host_availability(self, host_id: str) -> bool:
        """检查主机是否可用（简化版：检查是否可预约）"""
        try:
            details = self.get_host_details(host_id)
            # 如果reservable字段为True，则认为可用
            return details.get('reservable', 'False') == 'True'
        except Exception:
            return False
    
    def discover_resources(self, site: Optional[str] = None) -> Dict[str, Any]:
        """Discover resources (simplified version using Blazar client)"""
        if site is None:
            site = self.default_site
        
        print(f"\nDiscovering resources at {site} site...")
        
        # Get all hosts
        hosts = self.list_reservation_hosts()
        print(f"✓ Found {len(hosts)} hosts")
        
        # Extract unique node_types
        node_types = set()
        for host in hosts:
            node_type = host.get('node_type', '')
            if node_type:
                node_types.add(node_type)
        
        print(f"✓ Discovered {len(node_types)} node types: {', '.join(sorted(node_types))}")
        
        return {
            'site': site,
            'total_hosts': len(hosts),
            'node_types': sorted(list(node_types)),
            'hosts': hosts
        }
    
    def extract_resource_properties(self, hosts: List[Dict[str, Any]]) -> Dict[str, set]:
        """提取资源属性集合"""
        properties = {
            'node_types': set(),
            'gpu_models': set(),
            'architectures': set(),
        }
        
        for host in hosts:
            # 提取node_type
            node_type = host.get('node_type', '')
            if node_type:
                properties['node_types'].add(node_type)
            
            # 提取GPU信息
            gpu_model = host.get('gpu.gpu_model', '')
            if gpu_model:
                properties['gpu_models'].add(gpu_model)
            
            # 提取架构信息
            arch = host.get('architecture.platform_type', '')
            if arch:
                properties['architectures'].add(arch)
        
        return properties
    
    def select_resources_with_ai(self, requirements: Dict[str, Any], 
                                  available_resources: Dict[str, Any]) -> Dict[str, Any]:
        """Use AI to select resources based on requirements"""
        
        hosts = available_resources.get('hosts', [])
        properties = self.extract_resource_properties(hosts)
        
        # Build resource information
        resource_info = f"""
Available node types: {', '.join(sorted(properties['node_types']))}
Available GPU models: {', '.join(sorted(properties['gpu_models'])) if properties['gpu_models'] else 'None'}
Available architectures: {', '.join(sorted(properties['architectures']))}
Total hosts: {len(hosts)}
"""
        
        system_prompt = """You are a cloud computing resource management expert.
Your task is to select the most suitable node type from available resources based on user hardware requirements.

Chameleon node type naming conventions:
- compute_*: General compute nodes (e.g., compute_cascadelake_r640, compute_skylake)
- gpu_*: GPU nodes (e.g., gpu_rtx_6000, gpu_a100_pcie)
- storage_*: Storage-optimized nodes

Return JSON format:
{
    "node_type": "selected node type (exact match from available list)",
    "reasoning": "selection rationale",
    "filter_expression": "JSON string format: [\\"=\\", \\"$node_type\\", \\"gpu_rtx_6000\\"]"
}

IMPORTANT: Use the EXACT node_type string from the available list. Do not abbreviate or modify it."""
        
        user_prompt = f"""User requirements:
- CPU cores: {requirements.get('cpu_cores', 'N/A')}
- RAM: {requirements.get('ram_gb', 'N/A')} GB
- GPU required: {requirements.get('gpu_required', False)}
- GPU memory: {requirements.get('gpu_memory_gb', 'N/A')} GB
- Disk: {requirements.get('disk_gb', 'N/A')} GB

Available resources:
{resource_info}

Select the most suitable node type. If GPU is required, prioritize GPU nodes. Return the EXACT node_type string from the available list."""
        
        try:
            response = self.ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            selection = self.ai_client.parse_json_response(response)
            
            print(f"\n✓ AI resource selection complete")
            print(f"  Node type: {selection.get('node_type', 'N/A')}")
            print(f"  Reasoning: {selection.get('reasoning', 'N/A')}")
            
            return selection
        except Exception as e:
            raise Exception(f"AI resource selection failed: {str(e)}")
    
    def filter_available_hosts(self, hosts: List[Dict[str, Any]], 
                                node_type: str) -> List[Dict[str, Any]]:
        """过滤出指定类型的可用主机"""
        filtered = []
        for host in hosts:
            if host.get('node_type') == node_type:
                # 检查是否可预约
                if host.get('reservable', 'False') == 'True':
                    filtered.append(host)
        return filtered
    
    def check_availability_batch(self, hosts: List[Dict[str, Any]], max_workers: int = 10) -> List[Dict[str, Any]]:
        """Batch check host availability using parallel requests"""
        available_hosts = []
        print(f"\nChecking availability of {len(hosts)} hosts in parallel...")
        
        def check_single_host(host):
            """Helper function to check a single host"""
            host_id = host.get('id', '')
            node_name = host.get('node_name', 'unknown')
            is_available = self.check_host_availability(host_id)
            return host, is_available, host_id, node_name
        
        # Use ThreadPoolExecutor for parallel checking
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_host = {executor.submit(check_single_host, host): host for host in hosts}
            
            # Process results as they complete
            completed = 0
            for future in as_completed(future_to_host):
                completed += 1
                try:
                    host, is_available, host_id, node_name = future.result()
                    if is_available:
                        available_hosts.append(host)
                        print(f"  [{completed}/{len(hosts)}] {node_name} (ID: {host_id}): ✓ Available")
                    else:
                        print(f"  [{completed}/{len(hosts)}] {node_name} (ID: {host_id}): ✗ Unavailable")
                except Exception as e:
                    print(f"  [{completed}/{len(hosts)}] Error checking host: {str(e)}")
        
        print(f"\n✓ Found {len(available_hosts)} available hosts")
        return available_hosts

