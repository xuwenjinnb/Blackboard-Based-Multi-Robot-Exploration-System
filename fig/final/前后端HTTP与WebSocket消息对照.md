# 前后端 HTTP 与 WebSocket 消息对照

本文整理本项目中前端 Vue 与后端 FastAPI 之间的通信方式。项目中前端主要不直接访问 Redis，也不直接调用 Robot、Controller、Navigator，而是通过 HTTP 和 WebSocket 与 FastAPI 通信。

总体关系如下：

```text
前端 Vue 页面
  ├─ HTTP 客户端 services/api.js
  │   └─ 主动发送登录、控制、配置、查询请求
  └─ WebSocket 客户端 services/ws.js
      └─ 接收后端持续推送的实时状态快照

后端 FastAPI backend/app/main.py
  ├─ HTTP 接口
  │   └─ 接收前端命令，读写 Redis 黑板
  └─ WebSocket 接口 /ws
      └─ 向前端推送 STATE_SNAPSHOT
```

## 一、基础文件位置

| 模块 | 文件位置 | 关键行 | 作用 |
|---|---|---:|---|
| 前端 API 地址配置 | `frontend/Pathfinding-Visualizer-ThreeJS-master/src/config/backend.js` | 3 | 定义 `API_BASE_URL` |
| 前端 WebSocket 地址配置 | `frontend/Pathfinding-Visualizer-ThreeJS-master/src/config/backend.js` | 5 | 定义 `WS_BASE_URL` |
| 前端 HTTP 封装 | `frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/api.js` | 14 | 定义统一 `request(path, options)` |
| 前端 WebSocket 封装 | `frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/ws.js` | 4 | 定义 `createSimulationSocket(...)` |
| 前端主页面调用入口 | `frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/PathfindingVisualizer.vue` | 240-255 | 引入 HTTP 和 WebSocket 方法 |
| 后端 FastAPI 主文件 | `backend/app/main.py` | 327、352、444、597、643 | 定义 HTTP 接口和 `/ws` |

## 二、HTTP 消息对照

HTTP 用于前端主动发起请求。特点是一次请求对应一次响应，适合登录、启动、暂停、修改配置、查询状态。

前端统一封装位置：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/api.js:14
```

核心逻辑：

```js
const response = await fetch(`${API_BASE_URL}${path}`, {
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  ...options,
});
```

也就是说，前端每个 HTTP 函数只需要传入接口路径、请求方法和请求体即可。

### 1. 登录与用户状态

| 前端消息函数 | 前端定义位置 | HTTP 接口 | 后端接收位置 | 请求内容 | 作用 |
|---|---|---|---|---|---|
| `login(username, password)` | `src/services/api.js:40` | `POST /auth/login` | `backend/app/main.py:352` | `{ username, password }` | 用户登录，后端返回 token 和用户信息 |
| `fetchCurrentUser()` | `src/services/api.js:47` | `GET /auth/me` | `backend/app/main.py:364` | 无请求体，带 Authorization | 查询当前登录用户 |
| `logout()` | `src/services/api.js:51` | `POST /auth/logout` | `backend/app/main.py:369` | 无请求体，带 Authorization | 退出登录，清除会话 |

登录页面实际调用位置：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/LoginView.vue:58-63
```

对应流程：

```text
用户输入账号密码
-> LoginView.vue 调用 api.login(...)
-> api.js 发送 POST /auth/login
-> main.py 的 login(...) 接收
-> AuthStore 校验用户
-> 返回 token 和 user
```

### 2. 状态查询

| 前端消息函数 | 前端定义位置 | HTTP 接口 | 后端接收位置 | 请求内容 | 作用 |
|---|---|---|---|---|---|
| `fetchState()` | `src/services/api.js:86` | `GET /state` | `backend/app/main.py:327` | 可选 `mapVersion`、`mapGeneration` | 获取当前黑板快照 |
| `fetchRuntime()` | `src/services/api.js:90` | `GET /runtime` | `backend/app/main.py:335` | 无请求体 | 获取运行参数，如策略、算法、地图尺寸 |

主页面初始化时先通过 HTTP 拉一次状态：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/PathfindingVisualizer.vue:428-434
```

对应流程：

```text
页面初始化
-> fetchState()
-> GET /state
-> FastAPI 读取 Redis 黑板
-> 返回完整 snapshot
-> 前端 applyBackendSnapshot(snapshot)
```

### 3. 仿真控制

| 前端消息函数 | 前端定义位置 | HTTP 接口 | 后端接收位置 | 请求内容 | 作用 |
|---|---|---|---|---|---|
| `startSimulation(payload)` | `src/services/api.js:94` | `POST /control/start` | `backend/app/main.py:597` | `{ policy, navigatorAlgorithm }` | 启动仿真，把系统状态写成 `RUNNING` |
| `pauseSimulation()` | `src/services/api.js:101` | `POST /control/pause` | `backend/app/main.py:614` | 无请求体 | 暂停仿真，把状态写成 `PAUSED` |
| `resumeSimulation()` | `src/services/api.js:105` | `POST /control/resume` | `backend/app/main.py:619` | 无请求体 | 继续仿真，把状态写成 `RUNNING` |
| `stopSimulation()` | `src/services/api.js:109` | `POST /control/stop` | `backend/app/main.py:624` | 无请求体 | 停止仿真，把状态写成 `STOPPED` |
| `resetSimulation()` | `src/services/api.js:113` | `POST /control/reset` | `backend/app/main.py:632` | 无请求体 | 重置仿真状态 |

主页面实际调用位置：

```text
PathfindingVisualizer.vue:522-532  启动
PathfindingVisualizer.vue:534-535  暂停
PathfindingVisualizer.vue:537-544  继续
PathfindingVisualizer.vue:546-547  停止
PathfindingVisualizer.vue:549-551  重置
```

启动消息示例：

```json
{
  "policy": "nearest",
  "navigatorAlgorithm": "baseline"
}
```

对应流程：

```text
用户点击启动
-> PathfindingVisualizer.vue 调用 handleBackendStart()
-> api.js 发送 POST /control/start
-> main.py 的 control_start(...) 接收
-> FastAPI 写 Redis 黑板 systemStatus = RUNNING
-> Robot / Controller / Navigator 看到 RUNNING 后开始工作
```

### 4. 策略与导航算法配置

| 前端消息函数 | 前端定义位置 | HTTP 接口 | 后端接收位置 | 请求内容 | 作用 |
|---|---|---|---|---|---|
| `setPolicy(policy)` | `src/services/api.js:117` | `POST /runtime/policy` | `backend/app/main.py:444` | `{ policy }` | 设置任务分配策略 |
| `setNavigatorAlgorithm(navigatorAlgorithm)` | `src/services/api.js:124` | `POST /runtime/navigator` | `backend/app/main.py:452` | `{ navigatorAlgorithm }` | 设置导航规划算法 |

主页面实际调用位置：

```text
PathfindingVisualizer.vue:553-554  切换任务分配策略
PathfindingVisualizer.vue:556-557  切换导航算法
```

消息示例：

```json
{
  "policy": "greedy"
}
```

```json
{
  "navigatorAlgorithm": "cbs"
}
```

### 5. 地图、小车、障碍物配置

| 前端消息函数 | 前端定义位置 | HTTP 接口 | 后端接收位置 | 请求内容 | 作用 |
|---|---|---|---|---|---|
| `setVehicles(payload)` | `src/services/api.js:131` | `POST /runtime/vehicles` | `backend/app/main.py:460` | `{ count, mode, positions }` | 配置小车数量和部署方式 |
| `setMap(payload)` | `src/services/api.js:138` | `POST /runtime/map` | `backend/app/main.py:476` | `{ width, height, chunkSize }` | 配置地图大小和分块 |
| `setObstacles(payload)` | `src/services/api.js:145` | `POST /runtime/obstacles` | `backend/app/main.py:492` | `{ mode, count, density, seed }` | 随机或手动配置障碍物 |
| `setObstacleCell(payload)` | `src/services/api.js:152` | `POST /runtime/obstacles/cell` | `backend/app/main.py:511` | `{ x, y, blocked }` | 单个格子切换障碍 |
| `setObstacleCells(payload)` | `src/services/api.js:159` | `POST /runtime/obstacles/cells` | `backend/app/main.py:529` | `{ cells: [...] }` | 批量刷障碍 |

主页面实际调用位置：

```text
PathfindingVisualizer.vue:559-563  应用小车配置
PathfindingVisualizer.vue:577-582  应用地图配置
PathfindingVisualizer.vue:614-621  随机障碍配置
PathfindingVisualizer.vue:672-683  批量刷障碍
```

消息示例：

```json
{
  "width": 50,
  "height": 50,
  "chunkSize": 10
}
```

```json
{
  "count": 8,
  "mode": "random"
}
```

```json
{
  "mode": "random",
  "count": 120,
  "seed": 1710000000000
}
```

## 三、WebSocket 消息对照

WebSocket 用于实时通信。项目中主要方向是：

```text
FastAPI 后端 -> 前端 Vue
```

也就是后端持续推送状态快照，前端收到后刷新地图、小车、任务、路径和事件面板。

### 1. 前端建立 WebSocket 连接

前端定义位置：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/ws.js:4
```

连接地址定义：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/ws.js:10
```

核心代码：

```js
socket = new WebSocket(`${WS_BASE_URL}/ws?token=${encodeURIComponent(getToken())}`);
```

说明：

```text
前端连接 /ws，并把登录 token 放在 query 参数中。
后端用 token 校验用户身份。
```

主页面实际创建连接：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/PathfindingVisualizer.vue:435-440
```

### 2. 后端定义 WebSocket 接口

后端定义位置：

```text
backend/app/main.py:643
```

核心逻辑：

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
```

连接建立后，后端先发送一份初始快照：

```text
backend/app/main.py:651-653
```

发送消息格式：

```json
{
  "type": "STATE_SNAPSHOT",
  "payload": {
    "map": {},
    "vehicles": [],
    "frontiers": [],
    "tasks": [],
    "navigationRequests": [],
    "navigationPlans": [],
    "heartbeats": [],
    "events": [],
    "systemStatus": "RUNNING",
    "runtime": {}
  }
}
```

### 3. 后端持续推送实时快照

后端推送循环位置：

```text
backend/app/main.py:691
```

核心发送位置：

```text
backend/app/main.py:713-714
```

核心逻辑：

```python
message = {"type": "STATE_SNAPSHOT", "payload": snapshot, "sentAt": now_ms()}
await websocket.send_json(message)
```

说明：

```text
FastAPI 周期性读取 Redis 黑板快照。
如果前端已经有旧地图版本，后端可以推送 mapDelta 增量。
前端收到 STATE_SNAPSHOT 后刷新页面状态。
```

### 4. 前端接收 WebSocket 消息

前端接收位置：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/ws.js:16-20
```

核心逻辑：

```js
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type === "STATE_SNAPSHOT" && onSnapshot) {
    onSnapshot(message.payload);
  }
};
```

主页面把 `onSnapshot` 绑定为：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/PathfindingVisualizer.vue:435-437
```

也就是：

```js
onSnapshot: this.applyBackendSnapshot
```

收到快照后的处理位置：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/components/PathfindingVisualizer.vue:447-450
```

作用：

```text
STATE_SNAPSHOT
-> applyBackendSnapshot(snapshot)
-> applySnapshot(snapshot, previousGrid)
-> 更新前端 store
-> 3D 地图、小车、路径、任务、事件面板刷新
```

### 5. WebSocket 控制消息

后端也支持前端通过 WebSocket 发送控制消息，但当前页面主要使用 HTTP 发控制命令。WebSocket 控制消息的后端接收位置如下：

```text
backend/app/main.py:655-658
backend/app/main.py:664-688
```

后端识别的格式：

```json
{
  "type": "CONTROL",
  "action": "start"
}
```

支持的 action：

| action | 后端处理位置 | 作用 |
|---|---:|---|
| `start` | `backend/app/main.py:666-673` | 启动仿真 |
| `pause` | `backend/app/main.py:674-675` | 暂停仿真 |
| `resume` | `backend/app/main.py:676-677` | 继续仿真 |
| `stop` | `backend/app/main.py:678-681` | 停止仿真 |
| `reset` | `backend/app/main.py:682-688` | 重置仿真 |

前端 WebSocket 封装中提供了发送函数：

```text
frontend/Pathfinding-Visualizer-ThreeJS-master/src/services/ws.js:47-50
```

但从当前主页面代码看，启动、暂停、继续、停止、重置主要调用的是 `api.js` 中的 HTTP 函数。

## 四、完整运行链路

### 1. 页面初始化

```text
PathfindingVisualizer.vue
-> fetchState()
-> GET /state
-> FastAPI 返回当前 Redis 黑板快照
-> applyBackendSnapshot(snapshot)
-> createSimulationSocket(...)
-> 连接 /ws
```

对应文件与行：

```text
PathfindingVisualizer.vue:428-440
api.js:86
main.py:327-332
ws.js:4-20
main.py:643-653
```

### 2. 用户点击启动

```text
用户点击启动
-> handleBackendStart()
-> startSimulation({ policy, navigatorAlgorithm })
-> POST /control/start
-> main.py control_start(...)
-> Redis 黑板 systemStatus = RUNNING
-> Robot / Controller / Navigator 开始工作
```

对应文件与行：

```text
PathfindingVisualizer.vue:522-532
api.js:94-98
main.py:597-611
```

### 3. 后端实时推送显示状态

```text
Robot / Controller / Navigator 写 Redis 黑板
-> FastAPI broadcast_loop 读取 snapshot
-> WebSocket 发送 STATE_SNAPSHOT
-> ws.js 接收消息
-> applyBackendSnapshot(snapshot)
-> 前端刷新 3D 可视化
```

对应文件与行：

```text
main.py:691-720
ws.js:16-20
PathfindingVisualizer.vue:447-450
```

## 五、答辩可用总结

本项目中前端和后端之间的通信分为 HTTP 和 WebSocket 两类。

HTTP 由前端 `src/services/api.js` 统一封装，主要发送登录、启动、暂停、恢复、重置、地图配置、小车配置、障碍物配置等主动请求；后端在 `backend/app/main.py` 中通过 `@app.get` 和 `@app.post` 定义对应接口并接收处理。

WebSocket 由前端 `src/services/ws.js` 建立长连接，连接到后端 `backend/app/main.py` 中的 `/ws` 接口。后端持续读取 Redis 黑板状态，并以 `STATE_SNAPSHOT` 消息推送给前端。前端收到快照后调用 `applyBackendSnapshot`，刷新 3D 地图、小车位置、任务、路径、frontier 和事件面板。

因此，这里的通信规律可以概括为：

```text
HTTP 负责前端主动发命令。
WebSocket 负责后端实时推状态。
FastAPI 负责接收 HTTP、维护 WebSocket，并读写 Redis 黑板。
```
