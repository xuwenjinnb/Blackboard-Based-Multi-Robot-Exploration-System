# Blackboard-Based Multi-Robot Exploration System

本项目是一个基于 Redis 黑板架构的多机器人协作探索仿真系统。系统面向未知栅格地图巡检场景，模拟多辆小车在未知环境中协作扫描、发现 frontier 前沿点、分配探索任务、规划路径，并通过 Web 前端实时展示地图覆盖率、车辆状态、任务队列、导航路径和系统事件。

项目的核心目标不是只做一个可视化界面，而是把多机器人探索过程拆分为低耦合的软件构件：API Gateway、Controller、Navigator 和 Robot Worker 之间不直接互相调用，而是通过 Redis 黑板读写共享状态。这种设计方便在单机上演示，也可以把不同组件部署到不同进程、终端或电脑上运行。

## 功能概览

- 多小车协作探索未知地图。
- 支持随机地图、障碍物和车辆部署。
- 支持实时显示地图覆盖率、行走步数、frontier、任务、路径和事件日志。
- 支持 `nearest`、`greedy`、`low_mdp` 等任务分配或探索策略。
- 支持 `baseline`、时空 A*、CBS 等路径规划方式。
- 支持启动、暂停、继续、停止和重置仿真。
- 支持 WebSocket 实时状态推送和 Three.js 3D 可视化。
- 支持 Redis 黑板式分布式部署。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端接口 | Python、FastAPI、Uvicorn |
| 状态中心 | Redis |
| 前端展示 | HTML、CSS、JavaScript、Three.js |
| 实时通信 | WebSocket |
| 路径规划 | A*、时空 A*、CBS |
| 任务策略 | nearest、greedy、low_mdp |

## 系统架构

```text
Frontend Dashboard
        |
        | HTTP / WebSocket
        v
FastAPI API Gateway
        |
        | read / write state
        v
Redis Blackboard
        ^
        |
        +-- Controller Worker
        |      读取车辆状态和 frontier，生成任务和导航请求
        |
        +-- Navigator Worker
        |      读取导航请求，规划路径并写回导航计划
        |
        +-- Robot Worker
               执行移动、扫描环境、上传地图 patch、发现 frontier
```

Redis 黑板中保存地图、车辆、frontier、任务、导航请求、导航计划、心跳和事件等运行状态。各组件只依赖黑板中的数据结构，不依赖彼此的进程地址，因此可以独立扩展和部署。

## 目录结构

```text
.
├── backend/                  # FastAPI 后端、仿真核心、黑板组件和 worker
├── frontend/                 # 前端页面和 Three.js 可视化资源
├── docker-compose.redis.yml  # Redis 启动配置
├── requirements.txt          # Python 依赖
├── run_backend.ps1           # 单机运行脚本
├── run_api_distributed.ps1   # 分布式 API 节点启动脚本
├── run_navigator_worker.ps1  # Navigator worker 启动脚本
├── run_robot_worker.ps1      # Robot worker 启动脚本
└── README.md
```

## 演示视频

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

## 运行方式

### 单机运行

单机模式下，Redis、FastAPI 和内嵌仿真调度运行在同一台电脑上，适合本地演示。

```powershell
docker compose -f docker-compose.redis.yml up -d
.\run_backend.ps1
```

浏览器访问：

```text
http://127.0.0.1:8000/dashboard
```

### 分布式运行

分布式模式下，API Gateway 和 Redis 可以部署在电脑 A，Controller、Navigator、Robot Worker 可以部署在电脑 B。下面以电脑 A 的 Redis 地址为 `192.168.192.54:6379` 为例。

电脑 A 启动 Redis 和 API Gateway：

```powershell
docker compose -f docker-compose.redis.yml up -d

.\run_api_distributed.ps1 -HostAddress 0.0.0.0 -Port 8000 -RedisUrl "redis://192.168.192.54:6379/0"
```

电脑 B 进入 `backend` 目录，连接电脑 A 的 Redis，并分别启动三个 worker：

```powershell
$redis = "redis://电脑A的IP:6379/0"

.\run_controller_worker.ps1 -RedisUrl $redis
.\run_navigator_worker.ps1 -RedisUrl $redis
.\run_robot_worker.ps1 -RedisUrl $redis
```

如果电脑 A 的 IP 就是 `192.168.192.54`，则电脑 B 可以写成：

```powershell
$redis = "redis://192.168.192.54:6379/0"

.\run_controller_worker.ps1 -RedisUrl $redis
.\run_navigator_worker.ps1 -RedisUrl $redis
.\run_robot_worker.ps1 -RedisUrl $redis
```

浏览器访问：

```text
http://电脑A的IP:8000/dashboard
```

说明：Robot Worker 是 fleet 模式，一个进程会管理 Redis 中配置好的全部小车，不需要为每辆小车单独启动一个进程。

## 核心策略

任务分配与探索策略：

- `nearest`：为空闲小车分配距离最近且可达的 frontier。
- `greedy`：综合距离和 frontier 附近未知区域收益进行选择。
- `low_mdp`：基于局部 MDP 价值迭代，让小车根据局部收益、移动代价和车辆排斥项自主选择下一步动作。

路径规划策略：

- `baseline`：基础路径规划流程。
- 时空 A*：在搜索中加入时间维度，用于降低多车路径冲突。
- CBS：Conflict-Based Search，用于多智能体路径规划中的冲突检测和分解求解。

## 项目亮点

- 黑板架构降低组件耦合，便于分布式部署。
- 多机器人可以同时探索未知地图，提高覆盖效率。
- 策略和路径规划算法可切换，便于比较不同算法效果。
- WebSocket 实时推送状态，Three.js 前端动态展示探索过程。
- 支持单机演示和跨电脑部署两种运行方式。
