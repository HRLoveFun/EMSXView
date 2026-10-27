# EMSXView Trading Tool - Quick Start

> **占位符约定**：`<repo-root>` 为仓库根（由仓库根的 `.emsxview-root` marker 定位，请替换为你的实际克隆路径）；`<host>` 默认 `localhost`；`<API_PORT>` / `<FRONTEND_PORT>` 默认 3000 / 5173，可由环境变量覆盖。完整约定见 [`docs/index.md` §7](./docs/index.md#7-占位符与可配置参数约定)。

## One-Command Start

```batch
# Navigate to project root（替换为你的实际克隆路径）
cd <repo-root>

# Launch the unified entry (restart + wait for frontend)
relaunch_service.bat
```

## Common Commands

| Action | Command |
|--------|---------|
| **Start** | `emsxview.bat start` |
| **Stop** | `emsxview.bat stop` |
| **Restart** | `emsxview.bat restart` or `relaunch_service.bat` |
| **Status** | `emsxview.bat status` |

## Service URLs

| Service | URL | Default | Port env var |
|---------|-----|---------|--------------|
| Frontend | `http://<host>:<FRONTEND_PORT>` | http://localhost:5173 | `npm run dev -- --port` |
| Backend API | `<API_BASE_URL>` | http://localhost:3000 | `API_PORT` |
| Health Check | `<API_BASE_URL>/api/health` | http://localhost:3000/api/health | `API_PORT` |

## Troubleshooting

### Port Already in Use
```batch
# Stop all services first
emsxview.bat stop

# Or force kill and restart
emsxview.bat restart
```

### Services Won't Start
```batch
# Check status
emsxview.bat status

# View logs
scripts\ops\service-manager.ps1 logs
```

### Connection Errors
1. Ensure backend is running first
2. Check Windows Firewall settings
3. Verify `.env` configuration

## Directory Structure

```
EMSXView/
├── emsxview.bat             # Unified entry (start/stop/restart/status)
├── relaunch_service.bat     # One-click restart (double-click)
├── package.json            # npm workspaces 根（frontend + ExecutionView 共用依赖树，lockfile 在仓库根）
├── ExecutionView/          # ExecutionView 模块（根级独立目录：module/ + standalone/）
├── frontend/               # React frontend（Shell + 共享层 + costview/marketview 模块）
├── backend/                # Python backend
│   └── api/                # FastAPI application
├── scripts/
│   └── ops/
│       └── service-manager.ps1 # PowerShell manager
└── logs/                   # Service logs
```

## Need Help?

- Full documentation: `docs/ops/service-management.md`
- API documentation: `backend/README.md`
- Frontend docs: `frontend/README.md`


