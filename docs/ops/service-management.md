# EMSXView Trading Tool - Service Management Guide

> Last updated: 2026-07-02 | 与 `CODEBUDDY.md` Build & Run Commands 章节对齐

## Quick Start

快速启动指南见 `QUICKSTART.md`（交互菜单）或 `scripts/ops/service-manager.ps1`（命令行）。
本文档专注服务架构细节和故障排查。

## Service Architecture

### Backend Service
- **Port**: 3000
- **Process**: Python (uvicorn)
- **Entry Point**: `backend/api/main.py`（或 `uvicorn main:app --port 3000`）
- **Health Check**: http://localhost:3000/api/health
- **Startup Time**: 通常几秒，但 Bloomberg 初始化和首轮订阅可能更久（30-120s）

### Frontend Service
- **Port**: 5173 (dev) / 80 (prod)
- **Process**: Node.js (Vite)
- **Entry Point**: `frontend/` (npm run dev)
- **Startup Time**: ~5 seconds

## Synchronized Startup Process

```
┌─────────────────────────────────────────────────────────────┐
│                    Service Startup Flow                      │
└─────────────────────────────────────────────────────────────┘

1. Check port availability
   ├── Port 3000 (backend) - must be free
   └── Port 5173 (frontend) - must be free

2. Start Backend
   ├── Launch Python process
   ├── Wait 3 seconds for initialization
   └── Health check (GET /api/health)

3. Start Frontend (only if backend is healthy)
   ├── Launch Node.js process
   ├── Wait 5 seconds for initialization
   └── Verify port is listening

4. Startup Complete
   ├── Backend: http://localhost:3000
   └── Frontend: http://localhost:5173
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

## Health Checks

### Backend Health Endpoint
```bash
# Check backend health
curl http://localhost:3000/api/health

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
curl http://localhost:5173

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
1. Install Node dependencies:
   ```bash
   cd frontend
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
   curl http://localhost:3000/api/health
   ```

2. Check CORS configuration in backend `.env`:
   ```
   ALLOWED_ORIGINS=http://localhost:5173,http://localhost:80
   ```

3. Restart both services:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "service-manager.ps1" restart
   ```

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
   cd backend/api
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
   nssm install EMSXViewBackend "python" "C:\path\to\EMSXView\backend\api\main.py"
   nssm install EMSXViewFrontend "node" "C:\path\to\EMSXView\frontend\node_modules\vite\bin\vite.js"
   ```

> 路径中的 `C:\path\to\EMSXView\` 需替换为实际仓库根。`ExecutionView\` 子目录已不再存在（2026 年 5 月重构后并入 `backend/api/`）；本节命令的 entry point 须使用 `main.py` 而非历史版本中的 `start_server.py`。

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
- `start-all.bat`: Quick start both services
- `stop-all.bat`: Quick stop both services
- `restart-all.bat`: Quick restart both services
- `check-status.bat`: Quick status check

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
3. Run status check: `scripts\check-status.bat`
