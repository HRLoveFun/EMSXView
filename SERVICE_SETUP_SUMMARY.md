# Service Management Setup Summary

## Created Files

### Main Service Manager
| File | Description |
|------|-------------|
| `scripts/service-manager.ps1` | PowerShell service manager with full functionality |
| `start-services.bat` | Interactive menu launcher (recommended) |

### Quick Batch Files
| File | Purpose |
|------|---------|
| `scripts/start-all.bat` | Quick start both services |
| `scripts/stop-all.bat` | Quick stop both services |
| `scripts/restart-all.bat` | Quick restart both services |
| `scripts/check-status.bat` | Quick status check |

### Documentation
| File | Description |
|------|-------------|
| `docs/SERVICE_MANAGEMENT.md` | Complete service management guide |
| `QUICKSTART.md` | Quick reference card |
| `SERVICE_SETUP_SUMMARY.md` | This file |

## Features

### Synchronized Startup
1. **Port Check**: Verifies ports 3000 and 5173 are free
2. **Backend First**: Starts Python backend and waits for health check
3. **Frontend Second**: Starts Node frontend only after backend is healthy
4. **Verification**: Confirms both services are running

### Synchronized Shutdown
1. **Frontend First**: Stops Node processes gracefully
2. **Backend Second**: Stops Python processes gracefully
3. **Port Cleanup**: Verifies ports are released
4. **Force Kill**: Handles stuck processes

### Port Conflict Resolution
- Automatic detection of port conflicts
- Shows which processes are using ports
- Can force kill conflicting processes
- Cleanup of zombie processes

### Health Monitoring
- Backend health check via `/api/health`
- Port listening verification
- Process status monitoring
- Log file tracking

## Usage Examples

### Interactive Mode (Recommended)
```batch
cd c:\Users\hrchen\Documents\EMSX
start-services.bat

# Then select:
# [1] Start Services
# [2] Stop Services
# [3] Restart Services
# [4] Check Status
# [5] View Logs
# [6] Exit
```

### Command Line Mode
```powershell
# Start services
cd scripts
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" start

# Stop services
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" stop

# Restart services
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" restart

# Check status
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" status

# Show logs
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" logs

# Force kill all
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" kill
```

### Quick Batch Mode
```batch
# From project root
scripts\start-all.bat    # Start services
scripts\stop-all.bat     # Stop services
scripts\restart-all.bat  # Restart services
scripts\check-status.bat # Check status
```

## Service Configuration

### Default Ports
- **Backend**: 3000 (Python/FastAPI)
- **Frontend**: 5173 (Vite dev server)

### Startup Timing
- **Backend**: Waits 3 seconds + health check
- **Frontend**: Waits 5 seconds after backend is ready

### Log Files
- **Location**: `logs/` directory
- **Backend**: `logs/backend-YYYYMMDD-HHMMSS.log`
- **Frontend**: `logs/frontend-YYYYMMDD-HHMMSS.log`

## Troubleshooting Commands

### Check Port Usage
```powershell
# Check port 3000
netstat -ano | findstr :3000

# Check port 5173
netstat -ano | findstr :5173
```

### Kill Process by Port
```powershell
# Kill process using port 3000
$proc = Get-NetTCPConnection -LocalPort 3000
Stop-Process -Id $proc.OwningProcess -Force
```

### Force Kill All Services
```batch
scripts\restart-all.bat
# Or
powershell -ExecutionPolicy Bypass -File "scripts/service-manager.ps1" kill
```

## Next Steps

1. **Test the setup**:
   ```batch
   cd c:\Users\hrchen\Documents\EMSX
   start-services.bat
   ```

2. **Access the application**:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:3000

3. **Monitor logs**:
   - Check `logs/` directory for service logs
   - Use option [5] in interactive menu

4. **Read full documentation**:
   - `docs/SERVICE_MANAGEMENT.md` for detailed guide
   - `QUICKSTART.md` for quick reference

## Integration with Exchange/Ticker Fix

The service manager works seamlessly with the Exchange/Ticker field fix:

1. Start services using service manager
2. Backend will load the fixed code with:
   - Enhanced Route model with enrichment fields
   - Improved data mapping logic
   - Delayed enrichment mechanism
3. Frontend will display data with proper defaults:
   - `route.ticker || '-'`
   - `route.exchange || '-'`

## Support

For issues:
1. Check service status: `scripts\check-status.bat`
2. Review logs in `logs/` directory
3. Consult `docs/SERVICE_MANAGEMENT.md`
4. Use force kill if needed: `scripts\restart-all.bat`
