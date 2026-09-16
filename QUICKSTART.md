# EMSXView Trading Tool - Quick Start

> **占位符约定**：`<repo-root>` 为仓库根（由仓库根的 `.emsxview-root` marker 定位，请替换为你的实际克隆路径）；`<host>` 默认 `localhost`；`<API_PORT>` / `<FRONTEND_PORT>` 默认 3000 / 5173，可由环境变量覆盖。完整约定见 [`docs/index.md` §7](./docs/index.md#7-占位符与可配置参数约定)。

## One-Command Start

```batch
# Navigate to project root（替换为你的实际克隆路径）
cd <repo-root>

# Launch interactive service manager
scripts\restart-all.bat
```

## Common Commands

| Action | Command |
|--------|---------|
| **Start** | `scripts\start-all.bat` or `relaunch_service.bat` |
| **Stop** | `scripts\stop-all.bat` |
| **Restart** | `scripts\restart-all.bat` or `relaunch_service.bat` |
| **Status** | `scripts\check-status.bat` |

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
scripts\stop-all.bat

# Or force kill
scripts\restart-all.bat
```

### Services Won't Start
```batch
# Check status
scripts\check-status.bat

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
├── relaunch_service.bat     # One-click restart
├── package.json            # npm workspaces 根（frontend + ExecutionView 共用依赖树，lockfile 在仓库根）
├── ExecutionView/          # ExecutionView 模块（根级独立目录：module/ + standalone/）
├── frontend/               # React frontend（Shell + 共享层 + costview/marketview 模块）
├── backend/                # Python backend
│   └── api/                # FastAPI application
├── scripts/
│   ├── start-all.bat       # Quick start
│   ├── stop-all.bat        # Quick stop
│   └── ops/
│       └── service-manager.ps1 # PowerShell manager
└── logs/                   # Service logs
```

## Need Help?

- Full documentation: `docs/ops/service-management.md`
- API documentation: `backend/README.md`
- Frontend docs: `frontend/README.md`


