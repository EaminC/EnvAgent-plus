#!/usr/bin/env python3
"""
自动硬件Provision工具 - 主入口程序

用法:
    python provision.py --repo <github_repo_url> [选项]

示例:
    python provision.py --repo https://github.com/user/project
    python provision.py --repo https://github.com/user/project --create-key --lease-name my-lease
"""
import argparse
import sys
import os
import subprocess
from pathlib import Path

# 导入所有模块
from config import load_config
from ai_client import AIClient
from key_manager import KeyManager
from repo_analyzer import RepoAnalyzer
from image_selector import ImageSelector
from resource_discovery import ResourceDiscovery
from network_manager import NetworkManager
from reservation_manager import ReservationManager
from server_launcher import ServerLauncher


def source_openrc(openrc_path: str) -> bool:
    """运行OpenRC脚本以设置环境变量"""
    print(f"\n{'='*60}")
    print(f"步骤 0: 设置Chameleon认证")
    print(f"{'='*60}")
    
    openrc_path = Path(openrc_path).expanduser()
    
    if not openrc_path.exists():
        raise FileNotFoundError(f"OpenRC文件不存在: {openrc_path}")
    
    print(f"✓ 找到OpenRC文件: {openrc_path}")
    print(f"\n请在终端中运行以下命令来设置环境变量:")
    print(f"  source {openrc_path}")
    print(f"\n然后重新运行此脚本。")
    
    # 检查是否已经设置了环境变量
    if 'OS_AUTH_URL' in os.environ:
        print(f"\n✓ 检测到OpenStack环境变量已设置")
        return True
    else:
        print(f"\n✗ 未检测到OpenStack环境变量")
        print(f"  请先运行: source {openrc_path}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='自动provision Chameleon裸金属服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（使用默认密钥）
  python provision.py --repo https://github.com/user/project
  
  # 创建新的SSH密钥
  python provision.py --repo https://github.com/user/project --create-key
  
  # 指定自定义配置
  python provision.py --repo https://github.com/user/project \\
      --key-name my-key --lease-name my-lease --server-name my-server
  
  # 使用.env配置文件
  python provision.py --repo https://github.com/user/project --env-file .env
        """
    )
    
    # 必需参数
    parser.add_argument('--repo', required=True, help='GitHub仓库URL')
    
    # 可选参数
    parser.add_argument('--env-file', help='.env配置文件路径')
    parser.add_argument('--create-key', action='store_true', help='创建新的SSH密钥对')
    parser.add_argument('--key-name', help='SSH密钥对名称（覆盖配置文件）')
    parser.add_argument('--key-path', help='SSH公钥路径（如果使用现有密钥）')
    parser.add_argument('--lease-name', help='租约名称（默认自动生成）')
    parser.add_argument('--server-name', help='服务器名称（默认自动生成）')
    parser.add_argument('--site', help='Chameleon站点（默认: uc）')
    parser.add_argument('--network', help='网络名称（默认: sharednet1）')
    parser.add_argument('--no-floating-ip', action='store_true', help='不分配浮动IP')
    parser.add_argument('--skip-repo-clone', action='store_true', help='跳过仓库克隆（用于测试）')
    
    args = parser.parse_args()
    
    try:
        # 加载配置
        print(f"\n{'='*60}")
        print(f"自动硬件Provision工具")
        print(f"{'='*60}")
        
        config = load_config(args.env_file)
        print(f"✓ 配置加载完成")
        
        # 检查OpenStack环境变量
        if not source_openrc(config.openrc_path):
            print(f"\n请先设置OpenStack环境变量，然后重新运行此脚本。")
            sys.exit(1)
        
        # 初始化AI客户端
        ai_client = AIClient(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
            model=config.openai_model
        )
        print(f"✓ AI客户端初始化完成")
        
        # ==================== 步骤 1: SSH密钥管理 ====================
        print(f"\n{'='*60}")
        print(f"步骤 1: SSH密钥管理")
        print(f"{'='*60}")
        
        key_manager = KeyManager()
        key_name = args.key_name or config.default_key_name
        
        if args.create_key:
            key_name = key_manager.ensure_keypair(key_name, create_new=True)
        else:
            key_path = args.key_path or config.default_key_path
            key_name = key_manager.ensure_keypair(key_name, public_key_path=key_path)
        
        # ==================== 步骤 2: 仓库分析 ====================
        print(f"\n{'='*60}")
        print(f"步骤 2: 分析GitHub仓库需求")
        print(f"{'='*60}")
        
        repo_analyzer = RepoAnalyzer(ai_client)
        
        if not args.skip_repo_clone:
            repo_path = repo_analyzer.clone_repo(args.repo)
        else:
            print(f"⚠ 跳过仓库克隆（测试模式）")
            repo_path = Path("/tmp/test-repo")
            repo_path.mkdir(exist_ok=True)
        
        requirements = repo_analyzer.analyze_requirements(repo_path)
        
        # ==================== 步骤 3: 镜像选择 ====================
        print(f"\n{'='*60}")
        print(f"步骤 3: 选择操作系统镜像")
        print(f"{'='*60}")
        
        image_selector = ImageSelector(ai_client)
        selected_image = image_selector.select_image_with_ai(requirements)
        
        # ==================== 步骤 4: 资源发现 ====================
        print(f"\n{'='*60}")
        print(f"步骤 4: 发现可用硬件资源")
        print(f"{'='*60}")
        
        site = args.site or config.default_site
        resource_discovery = ResourceDiscovery(ai_client, default_site=site)
        
        available_resources = resource_discovery.discover_resources(site)
        
        # ==================== 步骤 5: 资源选择 ====================
        print(f"\n{'='*60}")
        print(f"步骤 5: 选择合适的硬件资源")
        print(f"{'='*60}")
        
        resource_selection = resource_discovery.select_resources_with_ai(
            requirements, available_resources
        )
        
        node_type = resource_selection.get('node_type', '')
        filter_expression = resource_selection.get('filter_expression', '')
        
        # ==================== 步骤 6: 网络配置 ====================
        print(f"\n{'='*60}")
        print(f"步骤 6: 配置网络")
        print(f"{'='*60}")
        
        network_manager = NetworkManager()
        network_name = args.network or config.default_network
        network_id = network_manager.ensure_network(network_name)
        
        # ==================== 步骤 7: 创建预约 ====================
        print(f"\n{'='*60}")
        print(f"步骤 7: 创建硬件预约")
        print(f"{'='*60}")
        
        reservation_manager = ReservationManager(ai_client)
        
        # 确定租约时长
        duration_info = reservation_manager.determine_lease_duration_with_ai(requirements)
        
        # 创建租约
        lease_name = args.lease_name or f"auto-lease-{node_type}"
        lease = reservation_manager.create_lease(
            lease_name=lease_name,
            resource_properties=filter_expression,
            start_date=duration_info.get('start_date', 'now'),
            end_date=duration_info.get('end_date'),
            min_nodes=1,
            max_nodes=1
        )
        
        lease_id = lease.get('id', '')
        
        # 等待租约激活
        reservation_manager.wait_for_lease_active(lease_id)
        
        # 获取reservation ID
        reservation_id = reservation_manager.get_reservation_id_from_lease(lease_id)
        
        # ==================== 步骤 8: 启动服务器 ====================
        print(f"\n{'='*60}")
        print(f"步骤 8: 启动裸金属服务器")
        print(f"{'='*60}")
        
        server_launcher = ServerLauncher()
        server_name = args.server_name or f"auto-server-{node_type}"
        
        server = server_launcher.create_server(
            server_name=server_name,
            image_name=selected_image,
            key_name=key_name,
            network_id=network_id,
            reservation_id=reservation_id
        )
        
        server_id = server.get('id', '')
        
        # 等待服务器启动
        server_launcher.wait_for_server_active(server_id)
        
        # ==================== 步骤 9: 分配浮动IP ====================
        if not args.no_floating_ip:
            print(f"\n{'='*60}")
            print(f"步骤 9: 分配浮动IP")
            print(f"{'='*60}")
            
            floating_ip = network_manager.get_or_create_floating_ip()
            network_manager.attach_floating_ip(server_id, floating_ip)
            
            print(f"\n{'='*60}")
            print(f"✓ 服务器provision完成！")
            print(f"{'='*60}")
            print(f"服务器名称: {server_name}")
            print(f"服务器ID: {server_id}")
            print(f"浮动IP: {floating_ip}")
            print(f"SSH连接: ssh ubuntu@{floating_ip}")
            print(f"租约ID: {lease_id}")
            print(f"租约结束时间: {duration_info.get('end_date', 'N/A')}")
        else:
            print(f"\n{'='*60}")
            print(f"✓ 服务器provision完成！")
            print(f"{'='*60}")
            print(f"服务器名称: {server_name}")
            print(f"服务器ID: {server_id}")
            print(f"租约ID: {lease_id}")
            print(f"租约结束时间: {duration_info.get('end_date', 'N/A')}")
            print(f"\n注意: 未分配浮动IP，只能从Chameleon内部网络访问")
        
        # 保存信息到文件
        output_file = f"{server_name}_info.json"
        import json
        with open(output_file, 'w') as f:
            json.dump({
                'server_name': server_name,
                'server_id': server_id,
                'lease_id': lease_id,
                'reservation_id': reservation_id,
                'floating_ip': floating_ip if not args.no_floating_ip else None,
                'image': selected_image,
                'node_type': node_type,
                'key_name': key_name,
                'network_id': network_id,
                'end_date': duration_info.get('end_date'),
            }, f, indent=2)
        
        print(f"\n✓ 服务器信息已保存到: {output_file}")
        
    except KeyboardInterrupt:
        print(f"\n\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

