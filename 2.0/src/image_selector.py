"""
镜像选择模块
负责查询可用镜像并根据需求选择合适的镜像
"""
import subprocess
import json
from typing import List, Dict, Any, Optional
from ai_client import AIClient


class ImageSelector:
    """镜像选择器"""
    
    def __init__(self, ai_client: AIClient):
        """初始化镜像选择器"""
        self.ai_client = ai_client
    
    def list_images(self) -> List[Dict[str, str]]:
        """列出所有可用镜像"""
        try:
            result = subprocess.run(
                ['openstack', 'image', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            images = json.loads(result.stdout)
            # 只返回active状态的镜像
            return [img for img in images if img.get('Status') == 'active']
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出镜像失败: {e.stderr}")
    
    def get_image_details(self, image_name_or_id: str) -> Dict[str, Any]:
        """获取镜像详细信息"""
        try:
            result = subprocess.run(
                ['openstack', 'image', 'show', image_name_or_id, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取镜像详情失败: {e.stderr}")
    
    def filter_images_by_prefix(self, images: List[Dict[str, str]], prefix: str = "CC-") -> List[Dict[str, str]]:
        """过滤出指定前缀的镜像"""
        return [img for img in images if img['Name'].startswith(prefix)]
    
    def select_image_with_ai(self, requirements: Dict[str, Any]) -> str:
        """使用AI根据需求选择合适的镜像（两阶段选择）"""
        
        # 第一阶段：获取所有镜像并进行初步筛选
        all_images = self.list_images()
        cc_images = self.filter_images_by_prefix(all_images, "CC-")
        
        if not cc_images:
            raise Exception("未找到任何CC-开头的镜像")
        
        # 构建镜像列表字符串
        image_list = "\n".join([f"- {img['Name']} (ID: {img['ID']})" for img in cc_images])
        
        # 第一阶段：让AI选择符合模糊范围的镜像
        system_prompt_stage1 = """你是一个Linux系统管理员。
你的任务是根据用户的需求，从镜像列表中筛选出可能符合要求的镜像名称。

镜像命名规则：
- CC-Ubuntu20.04: Ubuntu 20.04基础镜像
- CC-Ubuntu22.04: Ubuntu 22.04基础镜像
- CC-Ubuntu24.04: Ubuntu 24.04基础镜像
- CC-Ubuntu20.04-CUDA: Ubuntu 20.04 + CUDA支持
- CC-Ubuntu22.04-CUDA: Ubuntu 22.04 + CUDA支持
- CC-Ubuntu24.04-CUDA: Ubuntu 24.04 + CUDA支持
- CC-CentOS7: CentOS 7基础镜像
- CC-CentOS8-stream: CentOS 8 Stream基础镜像
- 带日期后缀的是特定版本快照

请返回JSON格式的候选镜像列表：
{
    "candidates": ["镜像名1", "镜像名2", ...],
    "reasoning": "选择理由"
}

选择3-5个最合适的候选镜像。"""
        
        user_prompt_stage1 = f"""需求：
- 操作系统类型: {requirements.get('os_type', 'ubuntu')}
- 操作系统版本: {requirements.get('os_version', '22.04')}
- 需要CUDA: {requirements.get('cuda_required', False)}
- 需要GPU: {requirements.get('gpu_required', False)}

可用镜像列表：
{image_list}

请选择3-5个最合适的候选镜像。"""
        
        try:
            response_stage1 = self.ai_client.ask_with_context(
                system_prompt_stage1, 
                user_prompt_stage1, 
                temperature=0.3
            )
            stage1_result = self.ai_client.parse_json_response(response_stage1)
            candidates = stage1_result.get('candidates', [])
            
            print(f"\n✓ 第一阶段筛选完成，候选镜像: {len(candidates)} 个")
            print(f"  理由: {stage1_result.get('reasoning', 'N/A')}")
            
            if not candidates:
                raise Exception("第一阶段未找到合适的候选镜像")
            
            # 第二阶段：获取候选镜像的详细信息
            candidate_details = []
            for candidate_name in candidates:
                # 在原始列表中查找匹配的镜像
                matching_images = [img for img in cc_images if img['Name'] == candidate_name]
                if matching_images:
                    try:
                        details = self.get_image_details(matching_images[0]['ID'])
                        candidate_details.append({
                            'name': candidate_name,
                            'id': matching_images[0]['ID'],
                            'details': details
                        })
                    except Exception as e:
                        print(f"警告: 无法获取镜像 {candidate_name} 的详情: {e}")
            
            if not candidate_details:
                raise Exception("无法获取任何候选镜像的详细信息")
            
            # 构建详细信息字符串
            details_str = ""
            for candidate in candidate_details:
                details_str += f"\n\n=== {candidate['name']} ===\n"
                details_str += f"ID: {candidate['id']}\n"
                details = candidate['details']
                details_str += f"状态: {details.get('status', 'N/A')}\n"
                details_str += f"大小: {details.get('size', 'N/A')} bytes\n"
                details_str += f"磁盘格式: {details.get('disk_format', 'N/A')}\n"
                details_str += f"最小磁盘: {details.get('min_disk', 'N/A')} GB\n"
                details_str += f"最小内存: {details.get('min_ram', 'N/A')} MB\n"
                details_str += f"创建时间: {details.get('created_at', 'N/A')}\n"
            
            # 第二阶段：让AI从候选镜像中选择最终镜像
            system_prompt_stage2 = """你是一个Linux系统管理员。
你的任务是从候选镜像的详细信息中，选择最适合用户需求的单个镜像。

请返回JSON格式：
{
    "selected_image": "最终选择的镜像名称",
    "reasoning": "选择理由"
}"""
            
            user_prompt_stage2 = f"""需求：
- 操作系统类型: {requirements.get('os_type', 'ubuntu')}
- 操作系统版本: {requirements.get('os_version', '22.04')}
- 需要CUDA: {requirements.get('cuda_required', False)}
- 需要GPU: {requirements.get('gpu_required', False)}
- 最小磁盘: {requirements.get('disk_gb', 'N/A')} GB
- 最小内存: {requirements.get('ram_gb', 'N/A')} GB

候选镜像详细信息：
{details_str}

请从以上候选镜像中选择最合适的一个。优先选择：
1. 版本较新的镜像
2. 如果需要CUDA/GPU，必须选择带CUDA的镜像
3. 满足最小磁盘和内存要求的镜像"""
            
            response_stage2 = self.ai_client.ask_with_context(
                system_prompt_stage2,
                user_prompt_stage2,
                temperature=0.2
            )
            stage2_result = self.ai_client.parse_json_response(response_stage2)
            selected_image = stage2_result.get('selected_image', '')
            
            print(f"\n✓ 第二阶段选择完成")
            print(f"  最终镜像: {selected_image}")
            print(f"  理由: {stage2_result.get('reasoning', 'N/A')}")
            
            # 验证选择的镜像是否在候选列表中
            if selected_image not in candidates:
                print(f"警告: AI选择的镜像 {selected_image} 不在候选列表中，使用第一个候选镜像")
                selected_image = candidates[0]
            
            return selected_image
            
        except Exception as e:
            raise Exception(f"AI镜像选择失败: {str(e)}")
    
    def get_image_id(self, image_name: str) -> str:
        """根据镜像名称获取镜像ID"""
        images = self.list_images()
        for img in images:
            if img['Name'] == image_name:
                return img['ID']
        raise Exception(f"未找到镜像: {image_name}")

