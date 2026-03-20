# EMSX Log Optimization - Implementation Summary

**Date**: 2026-03-19  
**Status**: ✅ Completed  
**Space Saved**: ~130 MB (90% reduction)

---

## Changes Implemented

### 1. Storage Policy Revision

| Parameter | Before | After |
|-----------|--------|-------|
| Max file size | 10 MB | **5 MB** |
| Max backup files | 14 | **3** |
| Max age | 7 days | **3 days** |
| Total capacity | ~150 MB | **~20 MB** |
| Log level | INFO | **WARNING** |

**Files Modified**:
- `emsx-backend/backend/main.py` - Updated `_SizeAndAgeRotatingHandler` defaults
- `emsx-backend/.env` - Added configurable log environment variables
- `emsx-backend/.env.example` - Updated template with new settings

### 2. Folder Consolidation

**Before**:
```
EMSX/logs/                    (14 files, 140 MB)
EMSX/emsx-backend/backend/logs/  (4 files, 40 MB)
```

**After**:
```
EMSX/logs/                    (3-4 files, max 20 MB)
```

Logs now write to project root `logs/` folder only. Backend creates logs at `../../logs/` relative to its location.

**Files Modified**:
- `emsx-backend/backend/main.py` - Changed log path to use `LOG_DIR` environment variable
- `scripts/deploy/start-backend.ps1` - Updated to use root logs folder
- `emsx-backend/backend/start_server.py` - Updated log directory handling

### 3. Log Level Optimization

**Before**: All INFO logs captured (including every route enrichment)

**After**: 
- Default level: **WARNING**
- Configurable via `LOG_LEVEL` environment variable
- Startup banner logs configuration details

This reduces log volume by approximately **80-90%** during normal operation.

### 4. Cleanup Scripts

Created `scripts/cleanup-logs.ps1` for manual maintenance:
```powershell
# Dry run (preview what will be deleted)
.\scripts\cleanup-logs.ps1

# Execute cleanup
.\scripts\cleanup-logs.ps1 -Force
```

---

## Environment Configuration

Add these to your `emsx-backend/.env` file:

```bash
# =============================================================================
# Logging Configuration
# =============================================================================

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=WARNING

# Maximum log file size in bytes (5 MB)
LOG_MAX_BYTES=5242880

# Number of backup files to keep (3)
LOG_BACKUP_COUNT=3

# Maximum age of log files in days (3)
LOG_MAX_AGE_DAYS=3

# Log directory path (relative to backend/)
LOG_DIR=../../logs
```

---

## Backup Created

Pre-optimization backup saved as: `logs_backup_pre_optimization.zip`

Contains all log files before cleanup.

---

## Verification Steps

1. **Start the backend**:
   ```powershell
   .\scripts\deploy\start-backend.ps1
   ```

2. **Check logs are writing to correct location**:
   ```powershell
   Get-Content logs\emsx_api.log -Tail 20
   ```

3. **Verify new configuration is loaded**:
   - Look for startup message: `Logging configured: level=WARNING, max_bytes=5242880...`

4. **Test rotation** (optional):
   - Logs will rotate when they reach 5 MB
   - Maximum 3 backup files kept
   - Files older than 3 days auto-deleted

---

## Rollback Instructions

If issues occur, revert to previous settings:

1. Restore `.env` file from git: `git checkout emsx-backend/.env`
2. Restore `main.py`: `git checkout emsx-backend/backend/main.py`
3. Extract backup logs: `Expand-Archive logs_backup_pre_optimization.zip`

---

## Next Steps

1. **Monitor for 24-48 hours** to ensure logs capture errors correctly
2. **Adjust LOG_LEVEL** if needed:
   - Use `INFO` temporarily for debugging
   - Use `WARNING` for normal operation
   - Use `ERROR` for minimal logging
3. **Schedule cleanup script** (optional):
   ```powershell
   # Run daily at 3 AM
   $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File C:\Users\hrchen\Documents\EMSX\scripts\cleanup-logs.ps1 -Force"
   $Trigger = New-ScheduledTaskTrigger -Daily -At 3am
   Register-ScheduledTask -Action $Action -Trigger $Trigger -TaskName "EMSX-Log-Cleanup"
   ```

---

## Impact Summary

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Disk usage | ~150 MB/week | ~15 MB/week | **90% reduction** |
| Log files | 14-15 files | 3-4 files | **75% reduction** |
| Retention | 7 days | 3 days | Faster cleanup |
| Noise level | High (INFO) | Low (WARNING) | Clearer signal |
| Locations | 2 folders | 1 folder | Simplified |

---

## Files Modified

1. ✅ `emsx-backend/backend/main.py` - Logging configuration
2. ✅ `emsx-backend/.env` - Environment variables
3. ✅ `emsx-backend/.env.example` - Template
4. ✅ `emsx-backend/backend/start_server.py` - Startup script
5. ✅ `scripts/deploy/start-backend.ps1` - Deployment script
6. ✅ `docs/PROJECT_STRUCTURE.md` - Documentation
7. ✅ `logs/README.md` - Created
8. ✅ `scripts/cleanup-logs.ps1` - Created
