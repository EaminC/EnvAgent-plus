"""
仓库分析模块
负责克隆GitHub仓库并分析其环境需求
"""
import subprocess
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from ai_client import AIClient


class RepoAnalyzer:
    """仓库分析器"""
    
    def __init__(self, ai_client: AIClient):
        """初始化仓库分析器"""
        self.ai_client = ai_client
    
    def clone_repo(self, repo_url: str, target_dir: Optional[str] = None) -> Path:
        """克隆GitHub仓库"""
        if target_dir is None:
            # 从URL提取仓库名
            repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
            target_dir = f"/tmp/{repo_name}"
        
        target_path = Path(target_dir)
        
        # 如果目录已存在，先删除
        if target_path.exists():
            subprocess.run(['rm', '-rf', str(target_path)], check=True)
        
        try:
            subprocess.run(
                ['git', 'clone', repo_url, str(target_path)],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功克隆仓库到: {target_path}")
            return target_path
        except subprocess.CalledProcessError as e:
            raise Exception(f"克隆仓库失败: {e.stderr}")
    
    def find_environment_files(self, repo_path: Path) -> Dict[str, Optional[str]]:
        """查找环境相关文件"""
        files_to_check = [
            'README.md',
            'README.rst',
            'requirements.txt',
            'pyproject.toml',
            'setup.py',
            'environment.yml',
            'Dockerfile',
            '.python-version',
            'poetry.lock',
            'Pipfile',
            'package.json',
        ]
        
        found_files = {}
        for filename in files_to_check:
            file_path = repo_path / filename
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # 限制内容长度
                        if len(content) > 10000:
                            content = content[:10000] + "\n... (truncated)"
                        found_files[filename] = content
                except Exception as e:
                    print(f"警告: 无法读取 {filename}: {e}")
                    found_files[filename] = None
            else:
                found_files[filename] = None
        
        return found_files
    
    def analyze_requirements(self, repo_path: Path) -> Dict[str, Any]:
        """分析仓库的硬件和软件需求"""
        env_files = self.find_environment_files(repo_path)
        
        # 构建提示词
        files_content = ""
        for filename, content in env_files.items():
            if content:
                files_content += f"\n\n=== {filename} ===\n{content}"
        
        if not files_content:
            files_content = "未找到环境配置文件"
        
        system_prompt = """你是一个专业的系统管理员和DevOps工程师。
你的任务是分析GitHub仓库的环境配置文件，推断出运行该项目所需的硬件和软件资源。

请以JSON格式返回分析结果，包含以下字段：
{
    "cpu_cores": <最小CPU核心数，整数或null>,
    "ram_gb": <最小RAM大小(GB)，整数或null>,
    "gpu_required": <是否需要GPU，布尔值>,
    "gpu_memory_gb": <GPU显存需求(GB)，整数或null>,
    "disk_gb": <磁盘空间需求(GB)，整数或null>,
    "os_type": <操作系统类型，如"ubuntu", "centos"等>,
    "os_version": <操作系统版本，如"22.04", "20.04"等>,
    "cuda_required": <是否需要CUDA支持，布尔值>,
    "python_version": <Python版本要求，字符串或null>,
    "special_requirements": <特殊需求说明，字符串列表>
}

如果某个字段无法确定，请设置为null。请给出保守但合理的估计。"""
        
        user_prompt = f"""请分析以下仓库的环境配置文件，推断硬件和软件需求：

{files_content}

请返回JSON格式的分析结果。"""
        
        try:
            response = self.ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            requirements = self.ai_client.parse_json_response(response)
            
            print("\n✓ 仓库需求分析完成:")
            print(f"  CPU: {requirements.get('cpu_cores', 'N/A')} 核")
            print(f"  RAM: {requirements.get('ram_gb', 'N/A')} GB")
            print(f"  GPU: {'需要' if requirements.get('gpu_required') else '不需要'}")
            if requirements.get('gpu_required'):
                print(f"  GPU显存: {requirements.get('gpu_memory_gb', 'N/A')} GB")
            print(f"  磁盘: {requirements.get('disk_gb', 'N/A')} GB")
            print(f"  操作系统: {requirements.get('os_type', 'N/A')} {requirements.get('os_version', '')}")
            print(f"  CUDA: {'需要' if requirements.get('cuda_required') else '不需要'}")
            
            return requirements
        except Exception as e:
            raise Exception(f"分析需求失败: {str(e)}")

