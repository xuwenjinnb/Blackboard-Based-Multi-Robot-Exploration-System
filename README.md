# 多小车协作巡检仿真系统

本项目是软件构造实验的最终作业，实现了一个面向未知地图探索的多小车协作巡检仿真平台。系统通过 FastAPI 后端、Redis 黑板、分布式计算组件和 Three.js 前端界面，模拟多辆小车在未知环境中协作扫描、发现前沿点、分配巡检任务、规划路径并实时展示运行状态。

## 项目功能

- 支持地图大小、障碍物数量、小车数量等仿真参数配置。
- 支持随机生成障碍物和随机部署小车。
- 支持多小车协作探索未知地图，并实时统计覆盖率、步数、任务和事件。
- 支持 `nearest`、`greedy`、`low_mdp` 等任务分配或探索策略。
- 支持 `baseline`、时空 A*、CBS 等路径规划方式。
- 支持启动、暂停、继续、停止、重置等仿真控制。
- 支持 WebSocket 实时推送系统快照，前端 3D 可视化展示车辆、地图、frontier、任务和路径。
- 支持 Redis 黑板式通信，可将 API、Controller、Navigator、Robot 等组件拆分为独立进程运行。
- 支持回放数据记录，便于分析员查看历史仿真过程。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端接口 | Python、FastAPI、Uvicorn |
| 状态中心 | Redis |
| 前端展示 | HTML、CSS、JavaScript、Three.js |
| 实时通信 | WebSocket |
| 路径规划 | A*、时空 A*、CBS |
| 任务分配 | nearest、greedy、low_mdp |
| 测试 | pytest、httpx |
| 部署脚本 | PowerShell、Docker Compose |

## 目录结构

```text
最后一次作业/
├── backend/                  # FastAPI 后端、仿真核心、黑板组件和测试
│   ├── app/
│   │   ├── main.py           # 应用入口，挂载路由和前端静态资源
│   │   ├── simulation.py     # 内嵌仿真调度循环
│   │   ├── state.py          # 运行状态和领域数据结构
│   │   ├── pathfinding.py    # 基础路径规划能力
│   │   ├── controller/       # 任务分配组件与策略
│   │   ├── navigator/        # 导航组件与规划器
│   │   ├── robot/            # 小车执行与感知组件
│   │   ├── routers/          # HTTP 接口路由
│   │   └── workers/          # 分布式 worker 入口
│   └── tests/                # 后端测试用例
├── frontend/                 # 前端页面、Three.js 资源和构建产物
├── docker-compose.redis.yml  # Redis 启动配置
├── requirements.txt          # Python 依赖
├── run_backend.ps1           # 单机演示启动脚本
├── run_api_distributed.ps1   # 分布式 API 节点启动脚本
├── run_robot_worker.ps1      # Robot worker 启动脚本
└── run_navigator_worker.ps1  # Navigator worker 启动脚本
```

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- Docker Desktop
- PowerShell
- 现代浏览器，例如 Edge 或 Chrome

## 快速启动

在 PowerShell 中进入项目根目录：

```powershell
cd "C:\Users\Administrator\Desktop\Online continual learning\MOSE-master\3d\软件构造\实验\最后一次作业"
```

启动 Redis：

```powershell
docker compose -f docker-compose.redis.yml up -d
```

启动后端和前端服务：

```powershell
.\run_backend.ps1
```

如果 PowerShell 禁止执行脚本，可以先在当前窗口临时放开执行权限：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run_backend.ps1
```

启动成功后，在浏览器打开：

```text
http://127.0.0.1:8000/dashboard
```

也可以访问路径规划展示页面：

```text
http://127.0.0.1:8000/pathfinding
```

## 演示视频

项目根目录下提供了两段录制好的运行演示视频，可以直接在支持 HTML 视频标签的 Markdown 查看器中播放。如果当前查看器不支持内嵌播放，也可以点击视频链接打开。

### 基础策略演示

<video src="./2026-06-27 08-21-35.mp4" controls width="720"></video>

[打开基础策略演示视频](./2026-06-27%2008-21-35.mp4)

### 低层 MDP 策略演示

<video src="./2026-06-27 08-22-34.mp4" controls width="720"></video>

[打开低层 MDP 策略演示视频](./2026-06-27%2008-22-34.mp4)

## 默认账号

| 角色 | 账号 | 密码 | 用途 |
| --- | --- | --- | --- |
| 超级管理员 | `huadian` | `123456` | 管理运行员和分析员 |
| 系统运行员 | `operator` | `123456` | 配置地图、小车、算法并控制仿真 |
| 分析员 | `analyst` | `123456` | 查看历史仿真回放和运行数据 |

验收演示通常使用系统运行员账号：

```text
账号：operator
密码：123456
```

## 常用页面

| 地址 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000/dashboard` | 主控制台，用于验收演示和仿真控制 |
| `http://127.0.0.1:8000/pathfinding` | 3D 路径规划可视化页面 |
| `http://127.0.0.1:8000/state` | 当前系统状态快照 |
| `http://127.0.0.1:8000/runtime` | 当前运行策略和导航配置 |
| `http://127.0.0.1:8000/health/redis` | Redis 连接健康检查 |

## 单机运行流程

单机模式适合课程验收和本地演示。`run_backend.ps1` 会自动进入 `backend` 目录，创建或复用 `.venv`，安装依赖，并启动 FastAPI 服务。

推荐演示流程：

1. 打开 `http://127.0.0.1:8000/dashboard`。
2. 使用 `operator / 123456` 登录。
3. 配置地图大小、障碍物数量和小车数量。
4. 点击随机部署障碍物和随机部署车辆。
5. 选择任务策略，例如 `nearest` 或 `greedy`。
6. 选择导航算法，例如 `baseline` 或 `cbs`。
7. 点击启动，观察小车探索、frontier 变化、任务生成和路径规划。
8. 演示暂停、继续、重置等控制能力。

## 分布式运行

项目也支持低耦合分布式部署。核心思想是 FastAPI、Controller、Navigator、Robot 不直接互相调用，而是通过 Redis 黑板交换状态。

典型部署方式：

```text
电脑 A：FastAPI + 前端静态页面 + Redis 黑板
电脑 B：Controller Worker + Navigator Worker + Robot Fleet Worker
```

电脑 A 启动 API 节点：

```powershell
cd "C:\Users\Administrator\Desktop\Online continual learning\MOSE-master\3d\软件构造\实验\最后一次作业"
docker compose -f docker-compose.redis.yml up -d
.\run_api_distributed.ps1 -HostAddress 0.0.0.0 -Port 8000
```

电脑 B 连接电脑 A 的 Redis，并分别启动 worker：

```powershell
cd "电脑B上的项目路径\backend"

$redis = "redis://电脑A的IP:6379/0"

.\run_controller_worker.ps1 -RedisUrl $redis
.\run_navigator_worker.ps1 -RedisUrl $redis -BatchesPerTick 3
.\run_robot_worker.ps1 -RedisUrl $redis -StepsPerTick 1
```

浏览器访问：

```text
http://电脑A的IP:8000/dashboard
```

说明：Robot worker 是 fleet 模式，一个进程会管理 Redis 中配置好的全部小车，不需要为每辆小车单独启动一个进程。

## 系统架构

系统采用黑板式低耦合架构：

```text
前端 Dashboard
    |
    | HTTP / WebSocket
    v
FastAPI API Gateway
    |
    | 读写运行配置、控制命令、状态快照
    v
Redis Blackboard
    ^
    |
    +-- Robot Worker：扫描环境、移动小车、上传地图 patch、发现 frontier
    |
    +-- Controller Worker：读取车辆和 frontier，生成任务与导航请求
    |
    +-- Navigator Worker：读取导航请求，规划路径并写回导航计划
```

这种设计让各模块之间只依赖 Redis 中的共享状态，不依赖彼此的进程地址。单机时可以由后端内嵌仿真循环统一调度；分布式时可以把 Controller、Navigator、Robot 拆成独立 worker 运行。

## 核心算法

任务分配策略：

- `nearest`：为空闲车辆分配距离最近且可达的 frontier。
- `greedy`：综合距离和 frontier 周围未知区域收益进行选择。
- `low_mdp`：基于局部 MDP 价值迭代，让小车直接根据局部收益、移动代价和排斥项选择下一步动作。

路径规划策略：

- `baseline`：基础导航规划流程，通常结合 A* 或时空 A*。
- 时空 A*：在路径搜索中加入时间维度，降低多车路径冲突。
- CBS：Conflict-Based Search，用于多智能体路径规划中的冲突检测与分解求解。

## 测试

进入后端目录后运行测试：

```powershell
cd "C:\Users\Administrator\Desktop\Online continual learning\MOSE-master\3d\软件构造\实验\最后一次作业\backend"
.\.venv\Scripts\Activate.ps1
pytest
```

如果还没有创建虚拟环境，可以先运行根目录的 `.\run_backend.ps1`，它会自动创建 `.venv` 并安装依赖。

## 验收展示建议

建议按照以下顺序展示：

1. 介绍项目目标：多小车在未知地图中的协作巡检和实时可视化。
2. 登录 Dashboard，展示地图、小车、任务、路径、事件和指标面板。
3. 配置障碍物、小车数量、任务策略和路径规划算法。
4. 启动仿真，观察小车移动、地图覆盖率提升、frontier 生成和任务队列变化。
5. 演示暂停、继续、重置。
6. 切换 `nearest`、`greedy`、`low_mdp` 或 `baseline`、`cbs`，说明算法差异。
7. 打开后端代码，说明 FastAPI、Redis 黑板、Robot、Controller、Navigator 的职责划分。
8. 说明分布式低耦合改造：组件通过 Redis 通信，可以分进程、分终端、分电脑部署。

如果用于课程验收，建议重点说明 Redis 黑板、Robot、Controller、Navigator 的职责划分，以及策略切换前后的运行效果差异。

## 常见问题

### Redis 连接失败

确认 Docker Desktop 已启动，并执行：

```powershell
docker compose -f docker-compose.redis.yml up -d
```

然后访问：

```text
http://127.0.0.1:8000/health/redis
```

### 端口被占用

如果 `8000` 端口被占用，可以进入 `backend` 目录手动指定其他端口：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

然后访问：

```text
http://127.0.0.1:8010/dashboard
```

### PowerShell 不允许执行脚本

在当前 PowerShell 窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

再重新运行启动脚本。

## 项目亮点

- 使用 Redis 黑板实现组件解耦，便于扩展和分布式部署。
- 支持多小车协作探索，能直观看到覆盖率提升过程。
- 支持任务分配策略和路径规划算法切换，便于对比不同算法效果。
- 使用 WebSocket 推送实时状态，前端 3D 场景能动态展示探索过程。
- 提供回放和设计文档，既能展示运行效果，也能说明软件架构和算法依据。
