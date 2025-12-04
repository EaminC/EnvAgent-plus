# 自动硬件Provision工具

这是一个自动化工具，用于在Chameleon云上provision裸金属服务器。它使用AI分析GitHub仓库的需求，自动选择合适的硬件资源、操作系统镜像，并完成整个部署流程。

## 功能特性

1. **智能仓库分析**: 自动克隆GitHub仓库并分析环境需求（CPU、RAM、GPU、操作系统等）
2. **AI驱动的镜像选择**: 使用AI根据需求选择最合适的操作系统镜像
3. **自动资源发现**: 发现Chameleon云上的可用硬件资源
4. **智能资源匹配**: AI根据需求选择最合适的节点类型
5. **自动预约管理**: 创建和管理Blazar租约
6. **一键部署**: 自动完成从分析到服务器启动的全流程
7. **浮动IP管理**: 自动分配和配置公网访问

## 安装

### 前置要求

- Python 3.8+
- OpenStack CLI工具
- Chameleon账户和项目

### 安装依赖

```bash
cd /home/cc/EnvAgent-plus/src
pip install -r requirements.txt
```

### 配置

1. 复制配置文件模板：

```bash
cp env.example .env
```

2. 编辑 `.env` 文件，填入你的配置：

```bash
# OpenAI API配置（用于AI分析）
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=OpenAI/gpt-4o

# Chameleon配置文件路径
OPENRC_PATH=/path/to/your/openrc.sh

# SSH密钥配置
DEFAULT_KEY_NAME=my-key
DEFAULT_KEY_PATH=~/.ssh/id_rsa.pub

# 默认网络和站点
DEFAULT_NETWORK=sharednet1
DEFAULT_SITE=uc
```

3. 设置Chameleon环境变量：

```bash
source /path/to/your/openrc.sh
```

## 使用方法

### 基本用法

```bash
python provision.py --repo https://github.com/user/project
```

### 创建新的SSH密钥

```bash
python provision.py --repo https://github.com/user/project --create-key
```

### 指定自定义配置

```bash
python provision.py --repo https://github.com/user/project \
    --key-name my-key \
    --lease-name my-lease \
    --server-name my-server \
    --site uc \
    --network sharednet1
```

### 不分配浮动IP（仅内网访问）

```bash
python provision.py --repo https://github.com/user/project --no-floating-ip
```

### 使用自定义.env文件

```bash
python provision.py --repo https://github.com/user/project --env-file /path/to/.env
```

## 工作流程

工具执行以下步骤：

1. **步骤 0**: 设置Chameleon认证（检查OpenStack环境变量）
2. **步骤 1**: SSH密钥管理（创建或验证密钥对）
3. **步骤 2**: 分析GitHub仓库需求（克隆仓库，分析环境文件）
4. **步骤 3**: 选择操作系统镜像（AI两阶段选择）
5. **步骤 4**: 发现可用硬件资源（查询Chameleon API）
6. **步骤 5**: 选择合适的硬件资源（AI匹配需求）
7. **步骤 6**: 配置网络（获取网络ID）
8. **步骤 7**: 创建硬件预约（创建Blazar租约）
9. **步骤 8**: 启动裸金属服务器（创建实例）
10. **步骤 9**: 分配浮动IP（可选，用于公网访问）

## 命令行参数

### 必需参数

- `--repo`: GitHub仓库URL

### 可选参数

- `--env-file`: .env配置文件路径
- `--create-key`: 创建新的SSH密钥对
- `--key-name`: SSH密钥对名称（覆盖配置文件）
- `--key-path`: SSH公钥路径（如果使用现有密钥）
- `--lease-name`: 租约名称（默认自动生成）
- `--server-name`: 服务器名称（默认自动生成）
- `--site`: Chameleon站点（默认: uc）
- `--network`: 网络名称（默认: sharednet1）
- `--no-floating-ip`: 不分配浮动IP
- `--skip-repo-clone`: 跳过仓库克隆（用于测试）

## 输出

成功完成后，工具会：

1. 在终端显示服务器信息（名称、ID、IP地址等）
2. 保存详细信息到JSON文件（`<server_name>_info.json`）

示例输出：

```
============================================================
✓ 服务器provision完成！
============================================================
服务器名称: auto-server-gpu_rtx_6000
服务器ID: abc123...
浮动IP: 192.5.87.31
SSH连接: ssh ubuntu@192.5.87.31
租约ID: xyz789...
租约结束时间: 2025-12-05 12:00

✓ 服务器信息已保存到: auto-server-gpu_rtx_6000_info.json
```

## 模块说明

- `config.py`: 配置管理
- `ai_client.py`: AI客户端封装
- `key_manager.py`: SSH密钥管理
- `repo_analyzer.py`: 仓库分析
- `image_selector.py`: 镜像选择
- `resource_discovery.py`: 资源发现
- `network_manager.py`: 网络管理
- `reservation_manager.py`: 预约管理
- `server_launcher.py`: 服务器启动
- `provision.py`: 主入口程序

## 故障排除

### OpenStack环境变量未设置

```
✗ 未检测到OpenStack环境变量
请先运行: source /path/to/openrc.sh
```

**解决方案**: 运行 `source` 命令设置环境变量后重试。

### AI API密钥无效

```
错误: AI请求失败: Invalid API key
```

**解决方案**: 检查 `.env` 文件中的 `OPENAI_API_KEY` 是否正确。

### 密钥对已存在

```
错误: 创建密钥对失败: Keypair already exists
```

**解决方案**: 使用不同的密钥名称，或删除现有密钥对。

### 租约创建失败

```
错误: 创建租约失败: No available hosts
```

**解决方案**: 所选节点类型可能没有可用资源，尝试不同的时间段或节点类型。

## 注意事项

1. 确保你的Chameleon项目有足够的配额
2. 租约结束后服务器会自动删除，请及时保存数据
3. 浮动IP是共享资源，使用完毕后请释放
4. AI分析需要网络连接和有效的API密钥

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

