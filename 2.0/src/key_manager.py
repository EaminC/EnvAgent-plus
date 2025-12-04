"""
SSH密钥管理模块
负责创建、列出和管理OpenStack密钥对
"""
import subprocess
import json
from typing import Optional, List, Dict, Any
from pathlib import Path


class KeyManager:
    """SSH密钥管理器"""
    
    def __init__(self):
        """初始化密钥管理器"""
        pass
    
    def list_keypairs(self) -> List[Dict[str, str]]:
        """列出所有密钥对"""
        try:
            result = subprocess.run(
                ['openstack', 'keypair', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出密钥对失败: {e.stderr}")
    
    def keypair_exists(self, key_name: str) -> bool:
        """检查密钥对是否存在"""
        keypairs = self.list_keypairs()
        return any(kp['Name'] == key_name for kp in keypairs)
    
    def create_keypair_from_public_key(self, key_name: str, public_key_path: str) -> bool:
        """从现有公钥创建密钥对"""
        public_key_path = Path(public_key_path).expanduser()
        
        if not public_key_path.exists():
            raise FileNotFoundError(f"公钥文件不存在: {public_key_path}")
        
        try:
            subprocess.run(
                ['openstack', 'keypair', 'create', 
                 '--public-key', str(public_key_path), 
                 key_name],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功从 {public_key_path} 创建密钥对: {key_name}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"创建密钥对失败: {e.stderr}")
    
    def create_new_keypair(self, key_name: str, output_path: Optional[str] = None) -> str:
        """创建新的密钥对并保存私钥"""
        if output_path is None:
            output_path = f"{key_name}.pem"
        
        output_path = Path(output_path).expanduser()
        
        try:
            result = subprocess.run(
                ['openstack', 'keypair', 'create', key_name],
                capture_output=True,
                text=True,
                check=True
            )
            
            # 保存私钥
            with open(output_path, 'w') as f:
                f.write(result.stdout)
            
            # 设置权限
            output_path.chmod(0o600)
            
            print(f"✓ 成功创建新密钥对: {key_name}")
            print(f"✓ 私钥已保存到: {output_path}")
            return str(output_path)
        except subprocess.CalledProcessError as e:
            raise Exception(f"创建新密钥对失败: {e.stderr}")
    
    def delete_keypair(self, key_name: str) -> bool:
        """删除密钥对"""
        try:
            subprocess.run(
                ['openstack', 'keypair', 'delete', key_name],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功删除密钥对: {key_name}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"删除密钥对失败: {e.stderr}")
    
    def ensure_keypair(self, key_name: str, public_key_path: Optional[str] = None, 
                       create_new: bool = False) -> str:
        """确保密钥对存在
        
        Args:
            key_name: 密钥对名称
            public_key_path: 公钥路径（如果使用现有密钥）
            create_new: 是否创建新密钥对
            
        Returns:
            密钥对名称
        """
        if self.keypair_exists(key_name):
            print(f"✓ 密钥对已存在: {key_name}")
            return key_name
        
        if create_new:
            self.create_new_keypair(key_name)
        elif public_key_path:
            self.create_keypair_from_public_key(key_name, public_key_path)
        else:
            raise ValueError("必须指定 public_key_path 或设置 create_new=True")
        
        return key_name

