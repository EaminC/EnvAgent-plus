"""
预约管理模块
负责创建、查询和管理Blazar租约
"""
import subprocess
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ai_client import AIClient


class ReservationManager:
    """预约管理器"""
    
    def __init__(self, ai_client: AIClient):
        """初始化预约管理器"""
        self.ai_client = ai_client
    
    def list_leases(self) -> List[Dict[str, Any]]:
        """列出所有租约"""
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'lease', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"列出租约失败: {e.stderr}")
    
    def get_lease_details(self, lease_id: str) -> Dict[str, Any]:
        """获取租约详细信息"""
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'lease', 'show', lease_id, '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取租约详情失败: {e.stderr}")
    
    def get_host_allocation_list(self) -> List[Dict[str, Any]]:
        """获取主机分配列表"""
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'host', 'allocation', 'list', '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"获取主机分配列表失败: {e.stderr}")
    
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
    
    def determine_lease_duration_with_ai(self, requirements: Dict[str, Any]) -> Dict[str, str]:
        """使用AI确定租约时长"""
        
        current_time = datetime.now()
        
        system_prompt = """你是一个云资源管理专家。
你的任务是根据用户的需求和当前时间，确定合适的租约开始和结束时间。

请返回JSON格式：
{
    "start_date": "租约开始时间，格式: now 或 YYYY-MM-DD HH:MM",
    "end_date": "租约结束时间，格式: YYYY-MM-DD HH:MM",
    "duration_hours": "租约时长（小时）",
    "reasoning": "选择理由"
}

注意：
- 如果用户没有明确指定时长，建议默认24小时
- 开始时间通常使用 "now"
- 结束时间需要根据当前时间和时长计算"""
        
        user_prompt = f"""当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}

用户需求:
{json.dumps(requirements, indent=2, ensure_ascii=False)}

请确定合适的租约开始和结束时间。如果用户没有明确指定，建议24小时的租约。"""
        
        try:
            response = self.ai_client.ask_with_context(system_prompt, user_prompt, temperature=0.3)
            duration_info = self.ai_client.parse_json_response(response)
            
            # 如果AI返回的end_date不是绝对时间，我们自己计算
            if duration_info.get('start_date') == 'now':
                hours = int(duration_info.get('duration_hours', 24))
                end_time = current_time + timedelta(hours=hours)
                duration_info['end_date'] = end_time.strftime('%Y-%m-%d %H:%M')
            
            print(f"\n✓ AI确定租约时长")
            print(f"  开始时间: {duration_info.get('start_date', 'N/A')}")
            print(f"  结束时间: {duration_info.get('end_date', 'N/A')}")
            print(f"  时长: {duration_info.get('duration_hours', 'N/A')} 小时")
            print(f"  理由: {duration_info.get('reasoning', 'N/A')}")
            
            return duration_info
        except Exception as e:
            # 如果AI失败，使用默认值
            print(f"警告: AI确定时长失败，使用默认24小时: {str(e)}")
            end_time = current_time + timedelta(hours=24)
            return {
                'start_date': 'now',
                'end_date': end_time.strftime('%Y-%m-%d %H:%M'),
                'duration_hours': '24',
                'reasoning': '默认24小时租约'
            }
    
    def create_lease(self, lease_name: str, resource_properties: str,
                     start_date: str = "now", end_date: Optional[str] = None,
                     min_nodes: int = 1, max_nodes: int = 1) -> Dict[str, Any]:
        """创建租约
        
        Args:
            lease_name: 租约名称
            resource_properties: 资源属性过滤表达式，如 '["=", "$node_type", "gpu_rtx_6000"]'
            start_date: 开始时间
            end_date: 结束时间
            min_nodes: 最小节点数
            max_nodes: 最大节点数
        """
        if end_date is None:
            # 默认24小时后
            end_time = datetime.now() + timedelta(hours=24)
            end_date = end_time.strftime('%Y-%m-%d %H:%M')
        
        reservation_spec = (
            f"min={min_nodes},max={max_nodes},"
            f"resource_type=physical:host,"
            f"resource_properties='{resource_properties}'"
        )
        
        try:
            result = subprocess.run(
                ['openstack', 'reservation', 'lease', 'create',
                 '--reservation', reservation_spec,
                 '--start-date', start_date,
                 '--end-date', end_date,
                 lease_name,
                 '-f', 'json'],
                capture_output=True,
                text=True,
                check=True
            )
            lease = json.loads(result.stdout)
            print(f"\n✓ 成功创建租约: {lease_name}")
            print(f"  租约ID: {lease.get('id', 'N/A')}")
            print(f"  开始时间: {start_date}")
            print(f"  结束时间: {end_date}")
            return lease
        except subprocess.CalledProcessError as e:
            raise Exception(f"创建租约失败: {e.stderr}")
    
    def wait_for_lease_active(self, lease_id: str, timeout: int = 300) -> bool:
        """等待租约变为ACTIVE状态
        
        Args:
            lease_id: 租约ID
            timeout: 超时时间（秒）
        """
        import time
        
        print(f"\n等待租约 {lease_id} 激活...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                lease = self.get_lease_details(lease_id)
                status = lease.get('status', '')
                
                if status == 'ACTIVE':
                    print(f"✓ 租约已激活")
                    return True
                elif status == 'ERROR':
                    raise Exception(f"租约状态为ERROR")
                else:
                    print(f"  当前状态: {status}, 等待中...")
                    time.sleep(10)
            except Exception as e:
                print(f"  检查状态时出错: {e}")
                time.sleep(10)
        
        raise Exception(f"等待租约激活超时（{timeout}秒）")
    
    def get_reservation_id_from_lease(self, lease_id: str) -> str:
        """从租约中提取reservation ID"""
        lease = self.get_lease_details(lease_id)
        reservations = lease.get('reservations', [])
        
        if not reservations:
            raise Exception(f"租约 {lease_id} 中没有找到预约")
        
        reservation_id = reservations[0].get('id', '')
        if not reservation_id:
            raise Exception(f"无法从租约中提取reservation ID")
        
        print(f"✓ 提取到 reservation ID: {reservation_id}")
        return reservation_id
    
    def get_resource_id_from_lease(self, lease_id: str) -> str:
        """从租约中提取resource ID"""
        lease = self.get_lease_details(lease_id)
        reservations = lease.get('reservations', [])
        
        if not reservations:
            raise Exception(f"租约 {lease_id} 中没有找到预约")
        
        resource_id = reservations[0].get('resource_id', '')
        if not resource_id:
            raise Exception(f"无法从租约中提取resource ID")
        
        print(f"✓ 提取到 resource ID: {resource_id}")
        return resource_id
    
    def delete_lease(self, lease_id: str) -> bool:
        """删除租约"""
        try:
            subprocess.run(
                ['openstack', 'reservation', 'lease', 'delete', lease_id],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"✓ 成功删除租约: {lease_id}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"删除租约失败: {e.stderr}")

