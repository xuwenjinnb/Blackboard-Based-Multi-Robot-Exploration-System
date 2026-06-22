# 后端启动与用户权限

## 启动

1. 先启动 Redis，默认地址为 `redis://127.0.0.1:6379/0`。
2. 在 `backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

3. 浏览器打开 `http://127.0.0.1:8000/pathfinding`。

前端正式文件位于
`frontend/Pathfinding-Visualizer-ThreeJS-master/dist`。修改前端后需要重新执行：

```powershell
$env:NODE_OPTIONS="--openssl-legacy-provider"
npm.cmd run build
```

## 角色

- 超级管理员：默认账号 `huadian`，密码 `123456`，负责管理运行员和分析员。
- 系统运行员：默认账号 `operator`，密码 `123456`，用于 Dashboard 验收演示、地图配置、车辆配置、算法配置和仿真控制。
- 分析员：默认账号 `analyst`，密码 `123456`，查看每次仿真的地图、车辆、覆盖率、任务、导航和事件回放。

用户、登录会话、仿真黑板和回放数据都保存在 Redis 中。每次运行员启动仿真时创建一条回放，停止或重置时结束该回放。
