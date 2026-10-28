"""后端测试公共夹具：收口 SQLite 异步引擎，避免进程在汇总后挂死。

背景（2026-10-28 排查）：aiosqlite 的 `_connection_worker_thread` 是**非 daemon**
线程，连接未关闭时解释器退出阶段 `threading._shutdown` 会永久 join，表现为
pytest 打印汇总后进程不退出、并锁住 CWD（`backend/api`）导致 worktree 删不掉。
任何用例只要经 `db.get_db_session()` 惰性建过连接（含风控/决策日志等间接路径），
都必须把引擎 dispose 掉。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import traceback

import pytest


@pytest.fixture(autouse=True)
def _dispose_ops_engine():
    """每个用例结束后释放运营库异步引擎（无引擎时为空操作）。

    autouse fixture 的 teardown 晚于用例自身的 fixture，因此覆盖
    `importlib.reload(db)` 型夹具与隐式触发 `get_db_session()` 的代码路径。

    强制用独立 loop 而非 `asyncio.run`：后者退出时会把当前线程的隐式事件
    循环置空，使后续仍依赖 `asyncio.get_event_loop()` 的用例（如
    test_algo_scheduler）抛 "There is no current event loop"。
    """
    yield

    try:
        import db
    except ImportError:  # 无 SQLAlchemy / 独立子目录用例
        return
    if db._engine is None:  # 未建过引擎则无需收口，也不碰事件循环
        return
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(db.dispose_engine())
    finally:
        loop.close()


def _write(text: str) -> None:
    """输出到 stdout；目标流不支持中文（重定向为 cp1252 等）时退化为 ASCII 转义。

    守卫本身若因编码异常中断，进程仍会挂住——正是它要防的那种失败。
    """
    stream = sys.stdout
    try:
        stream.write(text)
    except UnicodeEncodeError:
        stream.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    stream.flush()


def pytest_sessionfinish(session, exitstatus):
    """守卫：仍残留 aiosqlite 工作线程时打印线程栈并强制退出。

    这类线程没有任何自动回收路径，直接返回会让进程永久挂住；强制以失败码
    退出可把「静默挂死」转成「可见失败」，否则 CI 会带着隐患继续保持绿色。
    """
    leaked = [t for t in threading.enumerate() if "_connection_worker_thread" in t.name]
    if not leaked:
        return

    frames = sys._current_frames()
    _write("\n[conftest] 检测到 aiosqlite 工作线程残留（非 daemon 线程，进程会永久挂住）：\n")
    for thread in leaked:
        _write(f"  - {thread.name} (daemon={thread.daemon})\n")
        frame = frames.get(thread.ident)
        if frame is not None:
            _write("".join(traceback.format_stack(frame)))
    _write("[conftest] 修复方式：创建异步引擎的夹具/用例在 teardown 调 `await db.dispose_engine()`。\n")
    os._exit(int(pytest.ExitCode.TESTS_FAILED))
