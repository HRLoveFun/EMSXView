# EMSXView Trading Tool - Quick Start

## One-Command Start

```batch
# Navigate to project root
cd c:\Users\hrchen\Documents\EMSXView

# Launch interactive service manager
scripts\restart-all.bat
```

## Common Commands

| Action | Command |
|--------|---------|
| **Start** | `scripts\start-all.bat` or `重启服务.bat` |
| **Stop** | `scripts\stop-all.bat` |
| **Restart** | `scripts\restart-all.bat` or `重启服务.bat` |
| **Status** | `scripts\check-status.bat` |

## Service URLs

| Service | URL | Port |
|---------|-----|------|
| Frontend | http://localhost:5173 | 5173 |
| Backend API | http://localhost:3000 | 3000 |
| Health Check | http://localhost:3000/api/health | - |

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
scripts\service-manager.ps1 logs
```

### Connection Errors
1. Ensure backend is running first
2. Check Windows Firewall settings
3. Verify `.env` configuration

## Directory Structure

```
EMSXView/
├── 重启服务.bat            # One-click restart
├── ExecutionView/
│   ├── backend/api/        # Python backend
│   └── frontend/           # React frontend
├── scripts/
│   ├── start-all.bat       # Quick start
│   ├── stop-all.bat        # Quick stop
│   └── service-manager.ps1 # PowerShell manager
└── logs/                   # Service logs
```

## Need Help?

- Full documentation: `docs/ops/service-management.md`
- API documentation: `ExecutionView/backend/README.md`
- Frontend docs: `ExecutionView/frontend/README.md`

