# EMSXView Trading Tool - Service Management Guide

> Last updated: 2026-10-20 | 与 [`AGENTS.md` §11 Build & Run Commands](../../AGENTS.md#11-build--run-commands) 对齐
>
> **占位符约定**（详见 [`docs/index.md` §7](../index.md#7-占位符与可配置参数约定)）：`<repo-root>` = 仓库根（由 `.emsxview-root` marker 定位）；`<host>` 默认 `localhost`；`<API_PORT>`=3000（`/api/health` 等端点基址记作 `<API_BASE_URL>`）、`<FRONTEND_PORT>`=5173（dev）/ 80（prod）。

## Quick Start

快速启动指南见 `QUICKSTART.md`（交互菜单）或 `scripts/ops/service-manager.ps1`（命令行）。
本文档专注服务架构细节和故障排查。

## Service Architecture

### Backend Service
- **Port**: `<API_PORT>`（默认 3000，覆盖变量 `API_PORT`）
- **Process**: Python (uvicorn)
- **Entry Point**: `<repo-root>/backend/api/main.py`（或 `uvicorn main:app --port <API_PORT>`）
- **Health Check**: `<API_BASE_URL>/api/health`
- **Startup Time**: 通常几秒，但 Bloomberg 初始化和首轮订阅可能更久（30-120s）

### Frontend Service
- **Port**: `<FRONTEND_PORT>`（dev 默认 5173 / prod 默认 80）
- **Process**: Node.js (Vite)
- **Entry Point**: `<repo-root>/frontend/` (npm run dev)
- **Startup Time**: ~5 seconds

### MarketView Service（2026-10-28 起纳入统一启停）
- **Port**: `<MARKETVIEW_PORT>`（默认 8001）
- **Process**: Python（`python main.py`）
- **Entry Point**: `<repo-root>/MarketView/main.py`
- **Ready 探针**: `<MARKETVIEW_BASE_URL>/openapi.json`（FastAPI 自带路由，不触库、不受鉴权影响）
- **依赖**: 不依赖 core backend 与 Bloomberg 会话；core 侧**没有** `/api/marketview/*` 桥接，只能独立运行
- **未启动的后果**: 前端 Market View 标签页**所有**数据面板返回 500（Vite 代理上游 `ECONNREFUSED`），日志另见 §Troubleshooting
- **启停**: `emsxview.bat start|stop|restart|status` 与 `service-manager.ps1` 均已覆盖；启动失败只告警，不阻断 backend/frontend

## Synchronized Startup Process

```
┌─────────────────────────────────────────────────────────────┐
│                    Service Startup Flow                      │
└─────────────────────────────────────────────────────────────┘

1. Check port availability
   ├── Port <API_PORT> (backend, default 3000) - must be free
   └── Port <FRONTEND_PORT> (frontend, default 5173) - must be free

2. Start Backend
   ├── Launch Python process
   ├── Wait 3 seconds for initialization
   └── Health check (GET /api/health)

3. Start Frontend (only if backend is healthy)
   ├── Launch Node.js process
   ├── Wait 5 seconds for initialization
   └── Verify port is listening

4. Startup Complete
   ├── Backend: <API_BASE_URL>
   └── Frontend: http://<host>:<FRONTEND_PORT>
```

## Synchronized Shutdown Process

```
┌─────────────────────────────────────────────────────────────┐
│                   Service Shutdown Flow                      │
└─────────────────────────────────────────────────────────────┘

1. Stop Frontend First
   ├── Send SIGTERM to Node processes
   ├── Wait for graceful shutdown (2 seconds)
   └── Force kill if still running

2. Stop Backend
   ├── Send SIGTERM to Python processes
   ├── Wait for graceful shutdown (2 seconds)
   └── Force kill if still running

3. Port Cleanup
   ├── Verify port 3000 is released
   └── Verify port 5173 is released

4. Shutdown Complete
```

## Port Conflict Resolution

### Detecting Port Conflicts
The service manager automatically detects port conflicts:

```powershell
# Check what's using port 3000
netstat -ano | findstr :3000

# Check what's using port 5173
netstat -ano | findstr :5173
```

### Resolving Port Conflicts

#### Option 1: Automatic (via service manager)
```powershell
# The service manager will attempt to kill processes using these ports
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" stop
```

#### Option 2: Manual Kill
```powershell
# Find PID using port
$port = 3000
$proc = Get-NetTCPConnection -LocalPort $port | Select-Object -First 1
Stop-Process -Id $proc.OwningProcess -Force
```

#### Option 3: Force Kill All
```powershell
# Kill all Python and Node processes
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" kill
```

## Environment Configuration

### Development Mode (Default)
```powershell
# Uses:
# - Backend: port 3000
# - Frontend: port 5173 (Vite dev server)
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" start -Environment dev
```

### Production Mode
```powershell
# Uses:
# - Backend: port 3000
# - Frontend: port 80 (built files)
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" start -Environment prod
```

### Local Config Files (.env)

配置分两层，两个文件都被 `.gitignore` 忽略：

| 文件 | 内容 | 读取方 |
|------|------|--------|
| `<repo-root>/backend/.env` | 后端专属：`BLOOMBERG_*`、`API_PORT`、`API_WORKERS`；也兼容沿用其中的 `JWT_SECRET` | core backend（优先）、MarketView（回退） |
| `<repo-root>/.env` | 跨服务共享：`JWT_SECRET`、`BYPASS_AUTH` | core backend（补缺）、MarketView（优先） |

加载规则：`backend/.env` 优先，仓库根 `.env` 补缺；已存在的进程环境变量不被文件覆盖（临时覆盖直接 export/set 即可）。MarketView 优先读仓库根 `.env`，取不到 `JWT_SECRET` 时回退 `backend/.env`，兼容密钥只写在后端配置的既有部署。

**本地开发与鉴权**：前端没有登录页（设计前提是 Bloomberg 终端已本地认证），因此本地开发需在仓库根 `.env` 设置 `BYPASS_AUTH=true`，否则受保护端点（含 `/api/startup-status`、`/api/marketview/*`）返回 401。生产/共享环境必须保持 `false`（默认），两个服务行为一致：bypass 返回本地终端身份，非 bypass 一律 fail-closed。

前端若显示 `Startup chain error` 且消息为 `Authentication required`，即表示后端未开启 bypass 且浏览器未注入 token——这不是后端宕机。

## Health Checks

### Backend Health Endpoint
```bash
# Check backend health
curl <API_BASE_URL>/api/health

# Expected response:
{
  "success": true,
  "data": {
      "bloomberg": {
         "status": "connected"
      },
      "database": {
         "status": "disabled|connected|disconnected",
         "message": "DB persistence disabled|connected|<error>"
      }
  }
}
```

说明：

- 当 ENABLE_DB_PERSISTENCE=false 时，database.status 为 disabled，这是正常状态。
- 当前健康检查的核心含义是“服务可用 + Bloomberg 连接状态可见”，不是“本地必须连上 PostgreSQL”。

### Frontend Health
```bash
# Check frontend is serving
curl http://<host>:<FRONTEND_PORT>

# Should return HTML content
```

## Logging

### Log Locations
- **Backend Structured Logs**: `logs/emsx_api.log` 及其轮转文件
- **Frontend Dev Output**: Vite 终端输出
- **Service Wrapper Output**: 由 service-manager 或启动终端承接，不保证单独生成固定文件名

### Viewing Logs
```powershell
# View recent backend logs
Get-Content logs\emsx_api.log -Tail 50

# View all logs via service manager
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" logs
```

## Troubleshooting

### Issue: Backend fails to start
**Symptoms**: Port 3000 not responding

**Solutions**:
1. Check if port is already in use:
   ```powershell
   netstat -ano | findstr :3000
   ```

2. Kill existing process:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "service-manager.ps1" stop
   ```

3. Check Python dependencies:
   ```bash
   cd backend/api
   pip install -r requirements.txt
   ```

### Issue: Frontend fails to start
**Symptoms**: Port 5173 not responding

**Solutions**:
1. Install Node dependencies（npm workspaces：在**仓库根**执行；依赖提升到根 `node_modules`，frontend 与 ExecutionView 共用）:
   ```bash
   npm install
   ```

2. Check for port conflicts:
   ```powershell
   netstat -ano | findstr :5173
   ```

### Issue: Frontend can't connect to backend
**Symptoms**: Frontend shows connection errors

**Solutions**:
1. Verify backend is running:
   ```bash
   curl <API_BASE_URL>/api/health
   ```

2. Check CORS configuration in backend `.env`:
   ```
   ALLOWED_ORIGINS=http://<host>:<FRONTEND_PORT>,http://<host>:80
   ```

3. Restart both services:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "service-manager.ps1" restart
   ```

### Issue: Market View 标签页所有数据面板报 500 / "MarketView service unavailable"

原因：MarketView 微服务（`:8001`）未启动。前端 `/api/marketview/*` 由 Vite 代理转发，
上游不可达时代理返回 500——不是数据问题，也不是后端异常。

```powershell
# 1) 看状态（MarketView 段应显示 RUNNING / READY）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ops/service-manager.ps1 status -Environment dev

# 2) 拉起（幂等：已在运行会直接返回）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ops/service-manager.ps1 start -Environment dev

# 3) 单独启动（排查用）
cd MarketView; python main.py     # 日志：logs/service/marketview-*.log
```

判据：`curl http://localhost:8001/openapi.json` 返回 200 即服务就绪；若端口被占但
`/openapi.json` 无响应，说明是被别的进程占用，先 `stop` 或手工释放端口。

### Issue: Services start but stop immediately
**Symptoms**: Processes start then exit

**Solutions**:
1. Check backend logs for errors:
   ```bash
   cat logs/backend-*.log
   ```

2. Verify Bloomberg connection (if required):
   ```bash
   # Check BLOOMBERG_HOST in .env
   ```

3. Run backend manually to see errors:
   ```bash
   cd <repo-root>/backend/api
   python main.py
   ```

## Advanced Usage

### Custom Startup Delay
Edit `scripts/ops/service-manager.ps1`:
```powershell
$Config = @{
    Backend = @{
        StartupDelay = 5  # Increase if backend is slow
    }
    Frontend = @{
        StartupDelay = 10  # Increase if frontend is slow
    }
}
```

### Custom Ports
Edit `backend/.env`:
```
API_PORT=3001  # Change from default 3000
```

Edit `frontend/vite.config.ts`:
```typescript
server: {
    port: 5174,  // Change from default 5173
}
```

Then update `scripts/ops/service-manager.ps1`:
```powershell
$Config = @{
    Backend = @{
        Port = 3001
    }
    Frontend = @{
        DevPort = 5174
    }
}
```

### Windows Service Installation
To run as Windows Service (auto-start on boot):

1. Install NSSM (Non-Sucking Service Manager)
2. Create service:
   ```batch
   nssm install EMSXViewBackend "python" "<repo-root>\backend\api\main.py"
   nssm install EMSXViewFrontend "node" "<repo-root>\frontend\node_modules\vite\bin\vite.js"
   ```

> `<repo-root>` 需替换为实际仓库根（即包含 `.emsxview-root` marker 的目录，由 `Find-EmsxviewRoot` 解析得到），禁止写死具体磁盘路径。`ExecutionView\` 子目录已不再存在（2026 年 5 月重构后并入 `backend/api/`）；本节命令的 entry point 须使用 `main.py` 而非历史版本中的 `start_server.py`。

## Script Reference

### service-manager.ps1
Main PowerShell script with comprehensive service management.

**Parameters**:
- `Action`: start, stop, restart, status, logs, kill
- `Environment`: dev, prod
- `VerboseOutput`: Switch for detailed output

**Examples**:
```powershell
# Start in production mode with verbose output
.\service-manager.ps1 start -Environment prod -VerboseOutput

# Force kill all related processes
.\service-manager.ps1 kill

# Show recent logs
.\service-manager.ps1 logs
```

### Batch Files
- `emsxview.bat [start|stop|restart|status]`: unified entry in the repo root（默认 `status`；退出码透传自 `service-manager.ps1`）
- `relaunch_service.bat`: double-click wrapper — restart + wait for frontend + open the page

### relaunch_service.bat
One-click restart wrapper that delegates to `service-manager.ps1 restart` and waits for frontend readiness.
（仓库根实际文件名为 `relaunch_service.bat`，与早期文档中提到的 `重启服务.bat` 对应。）

## Best Practices

1. **Always use service manager**: Don't start services manually to ensure proper synchronization

2. **Check status before restart**: Use `status` action to verify current state

3. **Monitor logs**: Check logs when issues occur

4. **Graceful shutdown**: Always use `stop` action rather than killing processes manually

5. **Port cleanup**: If services crash, use `kill` action to clean up ports

6. **Environment consistency**: Use same environment (dev/prod) for both services

## Support

For issues or questions:
1. Check logs in `logs/` directory
2. Verify configuration in `.env` files
3. Run status check: `emsxview.bat status`
