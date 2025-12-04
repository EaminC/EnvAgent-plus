# 使用示例

## 场景1：部署一个深度学习项目

假设你有一个需要GPU的PyTorch项目：

```bash
# 使用快速启动脚本
./quick_start.sh https://github.com/pytorch/examples

# 或者直接使用Python
python3 provision.py --repo https://github.com/pytorch/examples
```

工具会：
1. 分析仓库，发现需要GPU和CUDA
2. 自动选择带CUDA的Ubuntu镜像（如CC-Ubuntu22.04-CUDA）
3. 选择GPU节点（如gpu_rtx_6000）
4. 创建租约并启动服务器
5. 分配浮动IP供外网访问

## 场景2：使用自定义SSH密钥

如果你想创建新的SSH密钥：

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --create-key \
    --key-name my-custom-key
```

如果你想使用现有的SSH密钥：

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --key-name my-existing-key \
    --key-path ~/.ssh/my_key.pub
```

## 场景3：指定租约名称和服务器名称

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --lease-name my-ml-experiment \
    --server-name ml-training-node
```

## 场景4：在不同站点部署

Chameleon有多个站点，你可以指定：

```bash
# 在UC站点部署
python3 provision.py --repo https://github.com/user/project --site uc

# 在TACC站点部署
python3 provision.py --repo https://github.com/user/project --site tacc
```

## 场景5：仅使用内网（不分配浮动IP）

如果你不需要从外网访问服务器：

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --no-floating-ip
```

这样可以节省浮动IP资源。

## 场景6：使用自定义.env配置

创建一个自定义配置文件 `my_config.env`：

```bash
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=OpenAI/gpt-4o
OPENRC_PATH=/home/user/my-openrc.sh
DEFAULT_KEY_NAME=my-key
DEFAULT_KEY_PATH=~/.ssh/id_rsa.pub
DEFAULT_NETWORK=sharednet1
DEFAULT_SITE=uc
```

然后使用：

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --env-file my_config.env
```

## 场景7：完整的端到端示例

```bash
# 1. 设置环境变量
source ~/CHI-251467-openrc.sh

# 2. 创建.env配置文件
cat > .env << EOF
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=forge-your-key-here
OPENAI_MODEL=OpenAI/gpt-4o
OPENRC_PATH=$HOME/CHI-251467-openrc.sh
DEFAULT_KEY_NAME=my-ml-key
DEFAULT_KEY_PATH=$HOME/.ssh/id_rsa.pub
DEFAULT_NETWORK=sharednet1
DEFAULT_SITE=uc
EOF

# 3. 运行provision工具
python3 provision.py \
    --repo https://github.com/pytorch/examples \
    --create-key \
    --lease-name pytorch-training \
    --server-name pytorch-gpu-node

# 4. 等待完成后，使用输出的浮动IP连接
# ssh ubuntu@<floating_ip>
```

## 场景8：测试模式（跳过仓库克隆）

用于快速测试工具功能：

```bash
python3 provision.py \
    --repo https://github.com/user/project \
    --skip-repo-clone
```

注意：这会跳过仓库分析，使用默认配置。

## 清理资源

provision完成后，服务器信息会保存到JSON文件。如果需要清理：

```bash
# 删除服务器
openstack server delete <server_name>

# 删除租约
openstack reservation lease delete <lease_id>

# 释放浮动IP
openstack floating ip delete <floating_ip>

# 删除密钥对（可选）
openstack keypair delete <key_name>
```

或者使用保存的JSON文件：

```bash
# 假设服务器信息保存在 auto-server-gpu_rtx_6000_info.json
SERVER_ID=$(jq -r '.server_id' auto-server-gpu_rtx_6000_info.json)
LEASE_ID=$(jq -r '.lease_id' auto-server-gpu_rtx_6000_info.json)
FLOATING_IP=$(jq -r '.floating_ip' auto-server-gpu_rtx_6000_info.json)

openstack server delete $SERVER_ID
openstack reservation lease delete $LEASE_ID
openstack floating ip delete $FLOATING_IP
```

## 故障排查

### 查看服务器日志

```bash
openstack console log show <server_name> --lines 100
```

### 查看租约状态

```bash
openstack reservation lease show <lease_id>
```

### 查看服务器状态

```bash
openstack server show <server_name>
```

### 查看可用资源

```bash
openstack reservation host list
```

## 高级用法

### 自定义AI模型

在.env文件中修改：

```bash
OPENAI_MODEL=OpenAI/gpt-4o-mini  # 使用更快的模型
```

### 修改默认租约时长

工具会使用AI根据项目需求确定租约时长，默认24小时。如果需要修改，可以在代码中调整`reservation_manager.py`的逻辑。

### 批量部署

创建一个脚本批量部署多个项目：

```bash
#!/bin/bash

REPOS=(
    "https://github.com/user/project1"
    "https://github.com/user/project2"
    "https://github.com/user/project3"
)

for repo in "${REPOS[@]}"; do
    echo "部署 $repo ..."
    python3 provision.py --repo "$repo"
    sleep 60  # 等待一分钟再部署下一个
done
```

