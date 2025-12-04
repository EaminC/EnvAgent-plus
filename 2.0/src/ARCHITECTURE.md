# 系统架构文档

## 概述

这是一个基于AI的自动化硬件provision工具，用于在Chameleon云平台上自动部署裸金属服务器。系统采用模块化设计，每个模块负责特定的功能。

## 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     provision.py (主入口)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ├─────────────────────────┐
                              │                         │
                              ▼                         ▼
                    ┌──────────────────┐      ┌──────────────────┐
                    │   config.py      │      │  ai_client.py    │
                    │  (配置管理)       │      │  (AI客户端)      │
                    └──────────────────┘      └──────────────────┘
                              │                         │
                              │                         │
        ┌─────────────────────┼─────────────────────────┼──────────────┐
        │                     │                         │              │
        ▼                     ▼                         ▼              ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│key_manager.py│    │ repo_analyzer.py │    │image_selector.py │    │resource_discovery│
│(密钥管理)     │    │  (仓库分析)      │    │  (镜像选择)      │    │  (资源发现)      │
└──────────────┘    └──────────────────┘    └──────────────────┘    └──────────────────┘
                              │                         │              │
                              └─────────────┬───────────┘              │
                                            │                          │
                                            ▼                          ▼
                                  ┌──────────────────┐    ┌──────────────────┐
                                  │network_manager.py│    │reservation_mgr.py│
                                  │  (网络管理)      │    │  (预约管理)      │
                                  └──────────────────┘    └──────────────────┘
                                            │                          │
                                            └─────────────┬────────────┘
                                                          │
                                                          ▼
                                                ┌──────────────────┐
                                                │server_launcher.py│
                                                │  (服务器启动)    │
                                                └──────────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────┐
                                                  │ OpenStack CLI│
                                                  │ Chameleon API│
                                                  └──────────────┘
```

## 模块说明

### 1. config.py - 配置管理模块

**职责**: 加载和管理配置信息

**主要功能**:
- 从.env文件或环境变量加载配置
- 提供配置数据类
- 支持配置覆盖

**关键类**:
- `Config`: 配置数据类
- `load_config()`: 配置加载函数

### 2. ai_client.py - AI客户端模块

**职责**: 封装与OpenAI兼容API的交互

**主要功能**:
- 发送聊天请求
- 解析JSON响应
- 处理API错误

**关键类**:
- `AIClient`: AI客户端类
  - `chat()`: 发送聊天请求
  - `ask_with_context()`: 带上下文的对话
  - `parse_json_response()`: 解析JSON响应

### 3. key_manager.py - SSH密钥管理模块

**职责**: 管理OpenStack SSH密钥对

**主要功能**:
- 列出现有密钥对
- 创建新密钥对
- 从公钥创建密钥对
- 删除密钥对

**关键类**:
- `KeyManager`: 密钥管理器
  - `list_keypairs()`: 列出密钥对
  - `create_keypair_from_public_key()`: 从公钥创建
  - `create_new_keypair()`: 创建新密钥对
  - `ensure_keypair()`: 确保密钥对存在

**对应API**: `<2.1A/B>` - Keys API

### 4. repo_analyzer.py - 仓库分析模块

**职责**: 克隆和分析GitHub仓库

**主要功能**:
- 克隆GitHub仓库
- 查找环境配置文件
- 使用AI分析硬件需求

**关键类**:
- `RepoAnalyzer`: 仓库分析器
  - `clone_repo()`: 克隆仓库
  - `find_environment_files()`: 查找环境文件
  - `analyze_requirements()`: 分析需求

**对应API**: `<0.1>` - Download Repo

### 5. image_selector.py - 镜像选择模块

**职责**: 查询和选择操作系统镜像

**主要功能**:
- 列出可用镜像
- 获取镜像详情
- 使用AI两阶段选择镜像

**关键类**:
- `ImageSelector`: 镜像选择器
  - `list_images()`: 列出镜像
  - `get_image_details()`: 获取详情
  - `select_image_with_ai()`: AI选择镜像

**对应API**: `<2.2.1>` 和 `<2.2.2>` - Images API

### 6. resource_discovery.py - 资源发现模块

**职责**: 发现和选择硬件资源

**主要功能**:
- 查询Chameleon API获取站点和节点信息
- 列出可预约的主机
- 使用AI匹配资源需求
- 检查主机可用性

**关键类**:
- `ResourceDiscovery`: 资源发现器
  - `get_sites()`: 获取站点
  - `get_nodes()`: 获取节点
  - `discover_resources()`: 发现资源
  - `select_resources_with_ai()`: AI选择资源
  - `check_availability_batch()`: 批量检查可用性

**对应API**: `<1.1>` - Resource Discovery API

### 7. network_manager.py - 网络管理模块

**职责**: 管理网络和浮动IP

**主要功能**:
- 列出和查询网络
- 创建和管理浮动IP
- 附加/分离浮动IP

**关键类**:
- `NetworkManager`: 网络管理器
  - `list_networks()`: 列出网络
  - `get_network_id()`: 获取网络ID
  - `create_floating_ip()`: 创建浮动IP
  - `attach_floating_ip()`: 附加浮动IP
  - `get_or_create_floating_ip()`: 获取或创建浮动IP

**对应API**: `<2.3.1>` - Networks API, `<4.2>` - Floating IP API

### 8. reservation_manager.py - 预约管理模块

**职责**: 管理Blazar租约

**主要功能**:
- 创建和查询租约
- 使用AI确定租约时长
- 等待租约激活
- 提取reservation ID

**关键类**:
- `ReservationManager`: 预约管理器
  - `list_leases()`: 列出租约
  - `create_lease()`: 创建租约
  - `determine_lease_duration_with_ai()`: AI确定时长
  - `wait_for_lease_active()`: 等待激活
  - `get_reservation_id_from_lease()`: 提取reservation ID

**对应API**: `<1.3.1>` - Reservations API

### 9. server_launcher.py - 服务器启动模块

**职责**: 创建和管理裸金属服务器

**主要功能**:
- 创建服务器实例
- 等待服务器启动
- 查询服务器状态
- 删除服务器

**关键类**:
- `ServerLauncher`: 服务器启动器
  - `create_server()`: 创建服务器
  - `wait_for_server_active()`: 等待启动
  - `get_server_details()`: 获取详情
  - `delete_server()`: 删除服务器

**对应API**: `<3.1>` - Bare Metal Instances API

### 10. provision.py - 主入口程序

**职责**: 协调所有模块完成端到端流程

**主要功能**:
- 解析命令行参数
- 按顺序调用各个模块
- 处理错误和异常
- 输出结果

**工作流程**:
1. 加载配置
2. 检查OpenStack环境
3. 管理SSH密钥
4. 分析仓库需求
5. 选择镜像
6. 发现资源
7. 选择硬件
8. 配置网络
9. 创建预约
10. 启动服务器
11. 分配浮动IP

## 数据流

```
GitHub Repo URL
      │
      ▼
[repo_analyzer] → Requirements (CPU, RAM, GPU, OS)
      │
      ├─────────────────┐
      │                 │
      ▼                 ▼
[image_selector]  [resource_discovery]
      │                 │
      │                 ▼
      │           [AI Resource Selection]
      │                 │
      ▼                 ▼
  Image Name      Node Type + Filter
      │                 │
      └────────┬────────┘
               │
               ▼
      [reservation_manager]
               │
               ▼
         Reservation ID
               │
               ▼
      [server_launcher]
               │
               ▼
         Server Instance
               │
               ▼
      [network_manager]
               │
               ▼
         Floating IP
```

## AI使用场景

系统在以下场景使用AI：

1. **仓库需求分析** (`repo_analyzer.py`)
   - 输入: 环境配置文件内容
   - 输出: 硬件和软件需求（JSON格式）

2. **镜像选择** (`image_selector.py`)
   - 第一阶段: 从所有镜像中筛选候选镜像
   - 第二阶段: 从候选镜像中选择最终镜像

3. **资源选择** (`resource_discovery.py`)
   - 输入: 用户需求 + 可用资源
   - 输出: 最合适的节点类型和过滤表达式

4. **租约时长确定** (`reservation_manager.py`)
   - 输入: 项目需求 + 当前时间
   - 输出: 开始时间、结束时间、时长

## API映射

| 模块 | 对应的Low-Level API | 说明 |
|------|-------------------|------|
| repo_analyzer | 0.1 | 下载和分析仓库 |
| resource_discovery | 1.1 | 资源发现 |
| reservation_manager | 1.2, 1.3 | 预约管理 |
| key_manager | 2.1 | 密钥管理 |
| image_selector | 2.2 | 镜像查询 |
| network_manager | 2.3, 4.1 | 网络和浮动IP |
| server_launcher | 3.1 | 裸金属实例 |

## 错误处理

系统在每个模块中都实现了错误处理：

1. **配置错误**: 缺少必需配置时抛出异常
2. **API错误**: OpenStack CLI失败时捕获stderr
3. **AI错误**: API调用失败时提供降级策略
4. **超时处理**: 等待资源就绪时设置超时
5. **用户中断**: 捕获Ctrl+C并优雅退出

## 扩展性

系统设计支持以下扩展：

1. **多站点支持**: 通过修改`resource_discovery.py`支持更多站点
2. **自定义AI模型**: 通过配置文件切换AI模型
3. **批量部署**: 通过脚本循环调用主程序
4. **自定义资源过滤**: 修改`resource_discovery.py`的过滤逻辑
5. **用户数据脚本**: 支持传入启动脚本

## 依赖关系

```
provision.py
├── config.py
├── ai_client.py
│   └── openai
├── key_manager.py
│   └── subprocess (openstack CLI)
├── repo_analyzer.py
│   ├── ai_client.py
│   └── subprocess (git)
├── image_selector.py
│   ├── ai_client.py
│   └── subprocess (openstack CLI)
├── resource_discovery.py
│   ├── ai_client.py
│   ├── requests (Chameleon API)
│   └── subprocess (openstack CLI)
├── network_manager.py
│   └── subprocess (openstack CLI)
├── reservation_manager.py
│   ├── ai_client.py
│   └── subprocess (openstack CLI)
└── server_launcher.py
    └── subprocess (openstack CLI)
```

## 性能考虑

1. **AI调用次数**: 系统总共进行4次AI调用
   - 仓库分析: 1次
   - 镜像选择: 2次（两阶段）
   - 资源选择: 1次
   - 租约时长: 1次

2. **API调用**: 主要瓶颈在等待资源就绪
   - 租约激活: 通常1-5分钟
   - 服务器启动: 通常10-30分钟

3. **优化策略**:
   - 缓存镜像列表
   - 并行检查主机可用性
   - 减少不必要的API调用

## 安全考虑

1. **密钥管理**: 私钥只保存在本地，不上传
2. **环境变量**: 敏感信息通过环境变量传递
3. **API密钥**: 存储在.env文件中，不提交到版本控制
4. **权限控制**: 使用OpenStack的项目隔离

## 未来改进

1. **Web界面**: 提供图形化界面
2. **状态持久化**: 保存中间状态，支持断点续传
3. **资源监控**: 监控服务器使用情况
4. **自动清理**: 租约到期前自动备份和清理
5. **多租户支持**: 支持多个项目和用户

