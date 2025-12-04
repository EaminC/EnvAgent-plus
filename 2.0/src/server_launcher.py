"""
服务器启动模块
负责创建和管理裸金属服务器实例
"""
import subprocess
import json
import time
from typing import Dict, Any, Optional


class ServerLauncher:
    """服务器启动器"""
    
    def __init__(self):
        """初始化服务器启动器"""
        pass
    
    def list_servers(self) -> list:
        """列出所有服务器"""
        try:
            result = subprocess.run(
                ['openstack', 'server', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出服务器失败: {e.stderr}")
    
    def get_server_details(self, server_name_or_id: str) -> Dict[str, Any]:
        """获取服务器详细信息"""
        try:
            result = subprocess.run(
                ['openstack', 'server', 'show', server_name_or_id, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取服务器详情失败: {e.stderr}")
    
    def create_server(self, 
                      server_name: str,
                      image_name: str,
                      key_name: str,
                      network_id: str,
                      reservation_id: str,
                      flavor: str = "baremetal",
                      user_data: Optional[str] = None) -> Dict[str, Any]:
        """创建裸金属服务器
        
        Args:
            server_name: 服务器名称
            image_name: 镜像名称
            key_name: SSH密钥对名称
            network_id: 网络ID
            reservation_id: 预约ID（注意：这是reservation的id，不是lease的id）
            flavor: 实例类型（默认baremetal）
            user_data: 用户数据脚本（可选）
        """
        cmd = [
            'openstack', 'server', 'create',
            '--image', image_name,
            '--flavor', flavor,
            '--key-name', key_name,
            '--nic', f'net-id={network_id}',
            '--hint', f'reservation={reservation_id}',
        ]
        
        if user_data:
            cmd.extend(['--user-data', user_data])
        
        cmd.extend([server_name, '-f', 'json'])
        
        try:
            print(f"\n正在创建服务器: {server_name}")
            print(f"  镜像: {image_name}")
            print(f"  密钥: {key_name}")
            print(f"  网络ID: {network_id}")
            print(f"  预约ID: {reservation_id}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            server = json.loads(result.stdout)
            
            print(f"\n✓ 服务器创建请求已提交")
            print(f"  服务器ID: {server.get('id', 'N/A')}")
            print(f"  状态: {server.get('status', 'N/A')}")
            
            return server
        except subprocess.CalledProcessError as e:
            raise Exception(f"创建服务器失败: {e.stderr}")
    
    def wait_for_server_active(self, server_name_or_id: str, timeout: int = 1800) -> bool:
        """等待服务器变为ACTIVE状态
        
        Args:
            server_name_or_id: 服务器名称或ID
            timeout: 超时时间（秒），默认30分钟
        """
        print(f"\n等待服务器 {server_name_or_id} 启动...")
        start_time = time.time()
        last_status = None
        
        while time.time() - start_time < timeout:
            try:
                server = self.get_server_details(server_name_or_id)
                status = server.get('status', '')
                
                # 只在状态变化时打印
                if status != last_status:
                    print(f"  当前状态: {status}")
                    last_status = status
                
                if status == 'ACTIVE':
                    print(f"✓ 服务器已启动")
                    # 打印地址信息
                    addresses = server.get('addresses', '')
                    if addresses:
                        print(f"  地址: {addresses}")
                    return True
                elif status == 'ERROR':
                    fault = server.get('fault', {})
                    raise Exception(f"服务器状态为ERROR: {fault}")
                else:
                    time.sleep(30)  # 每30秒检查一次
            except Exception as e:
                if 'ERROR' in str(e):
                    raise
                print(f"  检查状态时出错: {e}")
                time.sleep(30)
        
        raise Exception(f"等待服务器启动超时（{timeout}秒）")
    
    def delete_server(self, server_name_or_id: str) -> bool:
        """删除服务器"""
        try:
            subprocess.run(
                ['openstack', 'server', 'delete', server_name_or_id],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功删除服务器: {server_name_or_id}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"删除服务器失败: {e.stderr}")
    
    def get_server_console_log(self, server_name_or_id: str, lines: int = 50) -> str:
        """获取服务器控制台日志"""
        try:
            result = subprocess.run(
                ['openstack', 'console', 'log', 'show', 
                 '--lines', str(lines), server_name_or_id],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取控制台日志失败: {e.stderr}")

