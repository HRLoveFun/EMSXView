"""
Windows Task Scheduler Installer — register CostView daily update as a scheduled task.

Creates a Windows Scheduled Task that runs the daily_update.py script
at a configurable time (default: 18:00) every weekday.

Usage:
    python install_scheduler.py                     # Install with defaults
    python install_scheduler.py --time 17:30        # Custom time
    python install_scheduler.py --uninstall         # Remove the task
    python install_scheduler.py --status            # Check task status
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
_DAILY_UPDATE = _SCRIPT_DIR / "daily_update.py"

TASK_NAME = "CostView_DailyUpdate"


def _find_python() -> str:
    """Find the current Python executable path."""
    return sys.executable


def install_task(run_time: str = "18:00") -> bool:
    """Register the daily update task with Windows Task Scheduler.

    Args:
        run_time: Time in HH:MM format.

    Returns:
        True if registration succeeded.
    """
    python_exe = _find_python()

    # Build the schtasks command
    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python_exe}" "{_DAILY_UPDATE}" --once',
        "/sc", "weekly",
        "/d", "MON,TUE,WED,THU,FRI",
        "/st", run_time,
        "/f",  # force overwrite if exists
    ]

    print(f"Registering scheduled task: {TASK_NAME}")
    print(f"  Python:  {python_exe}")
    print(f"  Script:  {_DAILY_UPDATE}")
    print(f"  Time:    {run_time} (weekdays only)")
    print(f"  Command: {' '.join(cmd)}")
    print()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Task '{TASK_NAME}' registered successfully.")
            return True
        else:
            print(f"Failed to register task. Error:\n{result.stderr}")
            return False
    except FileNotFoundError:
        print("Error: schtasks.exe not found. Run from a Windows system.")
        return False


def uninstall_task() -> bool:
    """Remove the scheduled task."""
    cmd = ["schtasks", "/delete", "/tn", TASK_NAME, "/f"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Task '{TASK_NAME}' removed.")
            return True
        else:
            print(f"Failed to remove task: {result.stderr}")
            return False
    except FileNotFoundError:
        print("Error: schtasks.exe not found.")
        return False


def check_status() -> None:
    """Check the current status of the scheduled task."""
    cmd = ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"Task '{TASK_NAME}' not found or error:\n{result.stderr}")
    except FileNotFoundError:
        print("Error: schtasks.exe not found.")


def main():
    parser = argparse.ArgumentParser(
        description="Install/manage CostView daily update scheduled task"
    )
    parser.add_argument(
        "--time", type=str, default="18:00",
        help="Daily run time (HH:MM, default: 18:00)",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Remove the scheduled task",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check task status",
    )
    args = parser.parse_args()

    if args.status:
        check_status()
    elif args.uninstall:
        uninstall_task()
    else:
        install_task(run_time=args.time)


if __name__ == "__main__":
    main()
