# EMSX Trading Tool - Quick Start

## One-Command Start

```batch
# Navigate to project root
cd c:\Users\hrchen\Documents\EMSX

# Launch interactive service manager
start-services.bat
```

## Common Commands

| Action | Command |
|--------|---------|
| **Start** | `start-services.bat` → Select [1] |
| **Stop** | `start-services.bat` → Select [2] |
| **Restart** | `start-services.bat` → Select [3] |
| **Status** | `start-services.bat` → Select [4] |

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
start-services.bat → Select [2]

# Or force kill
scripts\restart-all.bat
```

### Services Won't Start
```batch
# Check status
start-services.bat → Select [4]

# View logs
start-services.bat → Select [5]
```

### Connection Errors
1. Ensure backend is running first
2. Check Windows Firewall settings
3. Verify `.env` configuration

## Directory Structure

```
EMSX/
├── start-services.bat      # Interactive launcher
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

