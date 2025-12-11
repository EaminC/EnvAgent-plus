"""
配置管理模块
负责加载环境变量和配置文件
"""
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class Config:
    """配置类"""
    # AI API配置
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    
    # Chameleon配置
    openrc_path: str
    
    # SSH密钥配置
    default_key_name: str
    default_key_path: str
    
    # 网络配置
    default_network: str
    default_site: str
    
    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Load configuration from environment variables or .env file"""
        # Auto-detect .env file if not specified
        if env_file is None:
            # Try to find .env in the same directory as this config file
            config_dir = Path(__file__).parent
            potential_env = config_dir / '.env'
            if potential_env.exists():
                env_file = str(potential_env)
        
        if env_file and os.path.exists(env_file):
            # Load .env file
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        # Strip quotes from value if present
                        value = value.strip().strip('"').strip("'")
                        os.environ[key.strip()] = value
        
        return cls(
            openai_base_url=os.getenv('OPENAI_BASE_URL', 'https://api.forge.tensorblock.co/v1'),
            openai_api_key=os.getenv('OPENAI_API_KEY', ''),
            openai_model=os.getenv('OPENAI_MODEL', 'OpenAI/gpt-4o'),
            openrc_path=os.getenv('OPENRC_PATH', '/home/cc/EnvAgent-plus/config/CHI-251467-openrc.sh'),
            default_key_name=os.getenv('DEFAULT_KEY_NAME', 'my-key'),
            default_key_path=os.getenv('DEFAULT_KEY_PATH', '~/.ssh/id_rsa.pub'),
            default_network=os.getenv('DEFAULT_NETWORK', 'sharednet1'),
            default_site=os.getenv('DEFAULT_SITE', 'uc'),
        )


def load_config(env_file: Optional[str] = None) -> Config:
    """加载配置"""
    return Config.from_env(env_file)

