#!/usr/bin/env python3
"""
Backend server startup script
"""
import os
import sys
from pathlib import Path

# Ensure log directory exists (respects LOG_DIR environment variable)
log_dir = os.getenv('LOG_DIR', '../../logs')
log_path = Path(log_dir).resolve()
os.makedirs(log_path, exist_ok=True)

# Start the server
if __name__ == "__main__":
    import uvicorn
    
    # Get log level from environment
    log_level = os.getenv('LOG_LEVEL', 'WARNING').lower()
    
    # Run the server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3000,
        workers=1,
        reload=False,
        log_level=log_level
    )
