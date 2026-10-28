"""后端测试公共夹具：收口 SQLite 异步引擎 + 定位非 daemon 线程泄漏。

背景（2026-10-28 排查）：aiosqlite 的 `_connection_worker_thread` 是**非 daemon**
线程，连接未关闭时解释器退出阶段 `threading._shutdown` 会永久 join，表现为
pytest 打印汇总后进程不退出、并锁住 CWD（`backend/api`）导致 worktree 删不掉。
本文件做两件事：

1. 每个用例结束后 dispose 运营库异步引擎，从源头掐断最常见的泄漏；
2. 会话结束时盘点残留线程：非 daemon 线程打印「归属用例 + 线程栈」后以失败码
   强制退出（否则进程会挂住），daemon 线程仅告警（不阻塞退出，属卫生问题）。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import traceback
from typing import Dict, List

import pytest

# 线程 ident -> 首次观察到它存活的用例 nodeid（泄漏归因用）
_THREAD_ORIGIN: Dict[int, str] = {}


def _alive_threads() -> List[threading.Thread]:
    """当前存活的非主线程。"""
    main = threading.main_thread()
    return [t for t in threading.enumerate() if t is not main and t.is_alive()]


def _dispose_ops_engine() -> None:
    """释放运营库异步引擎（无引擎时为空操作）。

    用独立 loop 而非 `asyncio.run`：后者退出会把当前线程的隐式事件循环置空，
    使仍依赖 `asyncio.get_event_loop()` 的用例（如 test_algo_scheduler）报
    "There is no current event loop"。
    """
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


@pytest.fixture(autouse=True)
def _isolate_background_resources(request):
    """用例级隔离：收口运营库引擎，并记录新起线程的归属用例。

    autouse fixture 的 teardown 晚于用例自身的 fixture，因此覆盖
    `importlib.reload(db)` 型夹具与隐式触发 `get_db_session()` 的代码路径；
    归属信息在会话结束时用于指出「哪个用例起的线程没停」。
    """
    before = {t.ident for t in threading.enumerate()}
    yield

    _dispose_ops_engine()
    for thread in threading.enumerate():
        if thread.ident not in before and thread.is_alive():
            _THREAD_ORIGIN.setdefault(thread.ident, request.node.nodeid)


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
    """盘点残留线程并给出归属；非 daemon 线程直接判失败并强制退出。"""
    leaked = _alive_threads()
    if not leaked:
        return

    blocking = [t for t in leaked if not t.daemon]
    _write(
        f"\n[conftest] 会话结束时仍有 {len(leaked)} 个非主线程存活（其中非 daemon {len(blocking)} 个）：\n"
    )
    frames = sys._current_frames()
    for thread in leaked:
        origin = _THREAD_ORIGIN.get(thread.ident, "未知（收集阶段或非用例代码创建）")
        _write(f"  - {thread.name} daemon={thread.daemon} origin={origin}\n")
        frame = frames.get(thread.ident)
        if frame is not None:
            _write("".join(traceback.format_stack(frame)))

    if not blocking:
        _write("[conftest] 均为 daemon 线程，不阻塞解释器退出；建议在用例 teardown 内 stop/join。\n")
        return

    _write(
        "[conftest] 非 daemon 线程未收口：若阻塞在无终止条件的等待上（实测 aiosqlite 工作线程即如此），\n"
        "          解释器退出阶段 threading._shutdown 会永久 join，进程挂住并锁住 CWD；已强制以失败码退出。\n"
        "[conftest] 修复方式：创建线程/引擎的夹具在 teardown 内 stop/join 或 `await db.dispose_engine()`。\n"
    )
    os._exit(int(pytest.ExitCode.TESTS_FAILED))
