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
            print(f"✓ Repository cloned to: {target_path}")
            return target_path
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to clone repository: {e.stderr}")
    
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
                    print(f"Warning: Cannot read {filename}: {e}")
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
            files_content = "No environment configuration files found"
        
        system_prompt = """You are a professional system administrator and DevOps engineer.
Your task is to analyze GitHub repository configuration files and infer the hardware and software resources needed to run the project.

Return analysis results in JSON format with the following fields:
{
    "cpu_cores": <minimum CPU cores, integer or null>,
    "ram_gb": <minimum RAM size (GB), integer or null>,
    "gpu_required": <whether GPU is needed, boolean>,
    "gpu_memory_gb": <GPU memory requirement (GB), integer or null>,
    "disk_gb": <disk space requirement (GB), integer or null>,
    "os_type": <OS type, e.g. "ubuntu", "centos">,
    "os_version": <OS version, e.g. "22.04", "20.04">,
    "cuda_required": <whether CUDA support is needed, boolean>,
    "python_version": <Python version requirement, string or null>,
    "special_requirements": <special requirements, string array>
}

If a field cannot be determined, set it to null. Provide conservative but reasonable estimates."""
        
        user_prompt = f"""Analyze the following repository configuration files and infer hardware and software requirements:

{files_content}

Return analysis results in JSON format."""
        
        try:
            response = self.ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            requirements = self.ai_client.parse_json_response(response)
            
            print("\n✓ Repository requirements analysis complete:")
            print(f"  CPU: {requirements.get('cpu_cores', 'N/A')} cores")
            print(f"  RAM: {requirements.get('ram_gb', 'N/A')} GB")
            print(f"  GPU: {'Required' if requirements.get('gpu_required') else 'Not required'}")
            if requirements.get('gpu_required'):
                print(f"  GPU Memory: {requirements.get('gpu_memory_gb', 'N/A')} GB")
            print(f"  Disk: {requirements.get('disk_gb', 'N/A')} GB")
            print(f"  OS: {requirements.get('os_type', 'N/A')} {requirements.get('os_version', '')}")
            print(f"  CUDA: {'Required' if requirements.get('cuda_required') else 'Not required'}")
            
            return requirements
        except Exception as e:
            raise Exception(f"Requirements analysis failed: {str(e)}")

