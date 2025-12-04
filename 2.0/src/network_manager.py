"""
网络和浮动IP管理模块
负责管理网络和浮动IP地址
"""
import subprocess
import json
from typing import List, Dict, Any, Optional


class NetworkManager:
    """网络管理器"""
    
    def __init__(self):
        """初始化网络管理器"""
        pass
    
    def list_networks(self) -> List[Dict[str, str]]:
        """列出所有网络"""
        try:
            result = subprocess.run(
                ['openstack', 'network', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出网络失败: {e.stderr}")
    
    def get_network_id(self, network_name: str) -> str:
        """根据网络名称获取网络ID"""
        networks = self.list_networks()
        for net in networks:
            if net['Name'] == network_name:
                return net['ID']
        raise Exception(f"未找到网络: {network_name}")
    
    def get_network_details(self, network_name_or_id: str) -> Dict[str, Any]:
        """获取网络详细信息"""
        try:
            result = subprocess.run(
                ['openstack', 'network', 'show', network_name_or_id, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取网络详情失败: {e.stderr}")
    
    def list_floating_ips(self) -> List[Dict[str, Any]]:
        """列出所有浮动IP"""
        try:
            result = subprocess.run(
                ['openstack', 'floating', 'ip', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出浮动IP失败: {e.stderr}")
    
    def create_floating_ip(self, network_name: str = "public") -> Dict[str, Any]:
        """创建新的浮动IP"""
        try:
            result = subprocess.run(
                ['openstack', 'floating', 'ip', 'create', network_name, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            floating_ip = json.loads(result.stdout)
            print(f"✓ 成功创建浮动IP: {floating_ip.get('floating_ip_address', 'N/A')}")
            return floating_ip
        except subprocess.CalledProcessError as e:
            raise Exception(f"创建浮动IP失败: {e.stderr}")
    
    def attach_floating_ip(self, server_name_or_id: str, floating_ip: str) -> bool:
        """将浮动IP附加到服务器"""
        try:
            subprocess.run(
                ['openstack', 'server', 'add', 'floating', 'ip', 
                 server_name_or_id, floating_ip],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功将浮动IP {floating_ip} 附加到服务器 {server_name_or_id}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"附加浮动IP失败: {e.stderr}")
    
    def detach_floating_ip(self, server_name_or_id: str, floating_ip: str) -> bool:
        """从服务器分离浮动IP"""
        try:
            subprocess.run(
                ['openstack', 'server', 'remove', 'floating', 'ip',
                 server_name_or_id, floating_ip],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功从服务器 {server_name_or_id} 分离浮动IP {floating_ip}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"分离浮动IP失败: {e.stderr}")
    
    def delete_floating_ip(self, floating_ip: str) -> bool:
        """删除浮动IP"""
        try:
            subprocess.run(
                ['openstack', 'floating', 'ip', 'delete', floating_ip],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功删除浮动IP: {floating_ip}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"删除浮动IP失败: {e.stderr}")
    
    def get_or_create_floating_ip(self) -> str:
        """获取未使用的浮动IP或创建新的"""
        # 检查是否有未使用的浮动IP
        floating_ips = self.list_floating_ips()
        for fip in floating_ips:
            if not fip.get('Fixed IP Address'):  # 未附加到任何服务器
                ip_address = fip.get('Floating IP Address', '')
                print(f"✓ 找到未使用的浮动IP: {ip_address}")
                return ip_address
        
        # 如果没有，创建新的
        new_fip = self.create_floating_ip()
        return new_fip.get('floating_ip_address', '')
    
    def ensure_network(self, network_name: str) -> str:
        """确保网络存在并返回其ID"""
        try:
            network_id = self.get_network_id(network_name)
            print(f"✓ 找到网络 {network_name}: {network_id}")
            return network_id
        except Exception as e:
            raise Exception(f"网络 {network_name} 不存在: {str(e)}")

