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
| **Start** | `start-services.bat` â†’ Select [1] |
| **Stop** | `start-services.bat` â†’ Select [2] |
| **Restart** | `start-services.bat` â†’ Select [3] |
| **Status** | `start-services.bat` â†’ Select [4] |

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
start-services.bat â†’ Select [2]

# Or force kill
scripts\restart-all.bat
```

### Services Won't Start
```batch
# Check status
start-services.bat â†’ Select [4]

# View logs
start-services.bat â†’ Select [5]
```

### Connection Errors
1. Ensure backend is running first
2. Check Windows Firewall settings
3. Verify `.env` configuration

## Directory Structure

```
EMSX/
â”œâ”€â”€ start-services.bat      # Interactive launcher
â”œâ”€â”€ ExecutionView/
â”‚   â”œâ”€â”€ backend/api/        # Python backend
â”‚   â””â”€â”€ frontend/           # React frontend
â”œâ”€â”€ scripts/
â”‚   â”œâ”€â”€ start-all.bat       # Quick start
â”‚   â”œâ”€â”€ stop-all.bat        # Quick stop
â”‚   â””â”€â”€ service-manager.ps1 # PowerShell manager
â””â”€â”€ logs/                   # Service logs
```

## Need Help?

- Full documentation: `docs/ops/service-management.md`
- API documentation: `ExecutionView/backend/README.md`
- Frontend docs: `ExecutionView/frontend/README.md`

