#!/bin/bash
# 快速启动脚本

set -e

echo "=========================================="
echo "自动硬件Provision工具 - 快速启动"
echo "=========================================="
echo ""

# 检查是否提供了仓库URL
if [ -z "$1" ]; then
    echo "用法: ./quick_start.sh <github_repo_url> [选项]"
    echo ""
    echo "示例:"
    echo "  ./quick_start.sh https://github.com/user/project"
    echo "  ./quick_start.sh https://github.com/user/project --create-key"
    echo ""
    exit 1
fi

REPO_URL=$1
shift  # 移除第一个参数，剩下的都是选项

# 检查OpenStack环境变量
if [ -z "$OS_AUTH_URL" ]; then
    echo "错误: OpenStack环境变量未设置"
    echo ""
    echo "请先运行:"
    echo "  source /path/to/your/openrc.sh"
    echo ""
    exit 1
fi

echo "✓ OpenStack环境变量已设置"
echo "  认证URL: $OS_AUTH_URL"
echo "  用户: $OS_USERNAME"
echo "  项目ID: $OS_PROJECT_ID"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3"
    exit 1
fi

echo "✓ Python已安装: $(python3 --version)"
echo ""

# 检查依赖
echo "检查依赖..."
if ! python3 -c "import openai" 2>/dev/null; then
    echo "警告: openai包未安装，正在安装依赖..."
    pip install -r requirements.txt
fi

echo "✓ 依赖检查完成"
echo ""

# 运行主程序
echo "启动provision工具..."
echo ""

python3 provision.py --repo "$REPO_URL" "$@"

