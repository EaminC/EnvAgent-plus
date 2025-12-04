"""
资源发现模块
负责发现Chameleon云上的可用硬件资源
"""
import subprocess
import json
import requests
from typing import List, Dict, Any, Optional
from ai_client import AIClient


class ResourceDiscovery:
    """资源发现器"""
    
    def __init__(self, ai_client: AIClient, default_site: str = "uc"):
        """初始化资源发现器"""
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
        """列出所有可预约的主机（使用OpenStack CLI）"""
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'host', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出预约主机失败: {e.stderr}")
    
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
        """发现资源（简化版：使用OpenStack CLI）"""
        if site is None:
            site = self.default_site
        
        print(f"\n正在发现 {site} 站点的资源...")
        
        # 获取所有主机
        hosts = self.list_reservation_hosts()
        print(f"✓ 找到 {len(hosts)} 个主机")
        
        # 提取唯一的node_type
        node_types = set()
        for host in hosts:
            node_type = host.get('node_type', '')
            if node_type:
                node_types.add(node_type)
        
        print(f"✓ 发现 {len(node_types)} 种节点类型: {', '.join(sorted(node_types))}")
        
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
        """使用AI根据需求选择资源"""
        
        hosts = available_resources.get('hosts', [])
        properties = self.extract_resource_properties(hosts)
        
        # 构建资源信息
        resource_info = f"""
可用节点类型: {', '.join(sorted(properties['node_types']))}
可用GPU型号: {', '.join(sorted(properties['gpu_models'])) if properties['gpu_models'] else '无'}
可用架构: {', '.join(sorted(properties['architectures']))}
总主机数: {len(hosts)}
"""
        
        system_prompt = """你是一个云计算资源管理专家。
你的任务是根据用户的硬件需求，从可用资源中选择最合适的节点类型。

Chameleon节点类型命名规则：
- compute_*: 通用计算节点
- gpu_*: GPU节点（如gpu_rtx_6000, gpu_a100等）
- storage_*: 存储优化节点

请返回JSON格式：
{
    "node_type": "选择的节点类型",
    "reasoning": "选择理由",
    "filter_expression": "OpenStack过滤表达式，格式如: [\\\"=\\\", \\\"$node_type\\\", \\\"gpu_rtx_6000\\\"]"
}"""
        
        user_prompt = f"""用户需求：
- CPU核心: {requirements.get('cpu_cores', 'N/A')}
- RAM: {requirements.get('ram_gb', 'N/A')} GB
- 需要GPU: {requirements.get('gpu_required', False)}
- GPU显存: {requirements.get('gpu_memory_gb', 'N/A')} GB
- 磁盘: {requirements.get('disk_gb', 'N/A')} GB

可用资源：
{resource_info}

请选择最合适的节点类型。如果需要GPU，请优先选择GPU节点。"""
        
        try:
            response = self.ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            selection = self.ai_client.parse_json_response(response)
            
            print(f"\n✓ AI资源选择完成")
            print(f"  节点类型: {selection.get('node_type', 'N/A')}")
            print(f"  理由: {selection.get('reasoning', 'N/A')}")
            
            return selection
        except Exception as e:
            raise Exception(f"AI资源选择失败: {str(e)}")
    
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
    
    def check_availability_batch(self, hosts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量检查主机可用性"""
        available_hosts = []
        print(f"\n正在检查 {len(hosts)} 个主机的可用性...")
        
        for i, host in enumerate(hosts, 1):
            host_id = host.get('id', '')
            node_name = host.get('node_name', 'unknown')
            
            if self.check_host_availability(host_id):
                available_hosts.append(host)
                print(f"  [{i}/{len(hosts)}] {node_name} (ID: {host_id}): ✓ 可用")
            else:
                print(f"  [{i}/{len(hosts)}] {node_name} (ID: {host_id}): ✗ 不可用")
        
        print(f"\n✓ 找到 {len(available_hosts)} 个可用主机")
        return available_hosts

