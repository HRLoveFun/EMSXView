"""日志配置幂等与轮转容错回归测试（2026-11-11）。

背景：`python main.py` 启动时，uvicorn 以 "main:app" 把同一文件二次 import
为模块 ``main``。旧实现第二次又创建了一个指向同一 emsx_api.log 的
RotatingFileHandler（句柄已打开但 basicConfig 未挂载）；Windows 下另一个
句柄占用导致 rollover rename 永远失败，日志停在 maxBytes，且每次 emit 都
向 stderr 打完整 traceback（service-manager 再把 stderr 写回日志），一天
放大到 32GB。
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def isolated_root_logger():
    """清空 root handlers，用例结束后还原并关闭本用例新增的 handler。"""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for handler in saved:
        root.removeHandler(handler)
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler not in saved:
                handler.close()
        for handler in saved:
            root.addHandler(handler)
        root.setLevel(saved_level)


def _load_main(monkeypatch, log_dir: Path, module_name: str):
    """按指定模块名执行一次 main.py（模拟 uvicorn 的二次 import）。"""
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # config.py 首次导入时校验 JWT_SECRET；模块已缓存时该设置无副作用
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    spec = importlib.util.spec_from_file_location(module_name, API_ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_second_module_execution_reuses_single_file_handler(
    isolated_root_logger, monkeypatch, tmp_path
):
    """二次执行 main.py 后，root 上指向同一日志文件的 handler 只能有一个。"""
    root = isolated_root_logger
    # pytest 的日志捕获会在调用阶段给 root 挂 handler；真实进程首次执行
    # main.py 时 root 为空，这里先还原成真实起点
    for handler in list(root.handlers):
        root.removeHandler(handler)

    log_dir = tmp_path / "logs"
    first = _load_main(monkeypatch, log_dir, "emsx_main_first")
    second = _load_main(monkeypatch, log_dir, "emsx_main_second")

    file_handlers = [h for h in root.handlers if getattr(h, "baseFilename", None)]

    assert len(file_handlers) == 1, f"同文件 handler 重复挂载: {file_handlers}"
    assert second._file_handler is first._file_handler
    assert second._file_handler is file_handlers[0]
    # 旧实现里第二个 handler 虽未挂载，却已打开文件句柄
    assert file_handlers[0].stream is not None
    assert (log_dir / "emsx_api.log").exists()

    # 二次配置不得新增控制台 handler
    console_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.StreamHandler) and not getattr(h, "baseFilename", None)
    ]
    assert len(console_handlers) == 1


@pytest.fixture
def main_module(isolated_root_logger, monkeypatch, tmp_path):
    """隔离 root logger 后加载一次 main.py，供轮转用例取 handler 类。"""
    return _load_main(monkeypatch, tmp_path / "logs", "emsx_main_for_rollover")


@pytest.mark.parametrize(
    "make_error",
    [
        lambda src, dst: PermissionError(32, "The process cannot access the file", src),
        lambda src, dst: FileNotFoundError(2, "No such file or directory", src),
    ],
    ids=["PermissionError", "FileNotFoundError"],
)
def test_do_rollover_swallows_recoverable_oserror_and_backs_off(
    main_module, tmp_path, make_error
):
    """rename 抛可恢复 OSError 时不外抛、不触发 handleError、不退避期内重复重试。"""
    handler_cls = main_module._SizeAndAgeRotatingHandler
    log_file = tmp_path / "rollover" / "emsx_api.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = handler_cls(
        str(log_file), max_bytes=200, backup_count=3, max_age_days=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    attempts: list[tuple[str, str]] = []

    def failing_rotate(src, dst):
        attempts.append((src, dst))
        raise make_error(src, dst)

    handler.rotate = failing_rotate
    handle_error_calls: list[logging.LogRecord] = []
    handler.handleError = handle_error_calls.append

    logger = logging.getLogger("test_rollover_failure")
    original_handlers = list(logger.handlers)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        for _ in range(20):
            logger.info("payload" * 40)
        handler.flush()

        assert attempts, "轮转从未被触发，用例未覆盖目标路径"
        assert len(attempts) == 1, "退避期内不应重复尝试 rename"
        assert handle_error_calls == [], "不该触发 logging.handleError"
        assert handler.stream is not None
        # 失败后恢复追加写入
        assert log_file.stat().st_size > 0
    finally:
        logger.handlers = original_handlers
        logger.propagate = True
        handler.close()


def test_do_rollover_still_rotates_and_purges_on_success(main_module, tmp_path):
    """正常轮转行为保持不变：生成 .1，并在成功后清理过期备份。"""
    handler_cls = main_module._SizeAndAgeRotatingHandler
    log_file = tmp_path / "rotate" / "emsx_api.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = handler_cls(
        str(log_file), max_bytes=100, backup_count=2, max_age_days=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    # Python 3.13 起空文件不轮转（gh-116263），先写入种子数据
    handler.stream.write("seed\n")
    handler.stream.flush()

    # 过期备份（超过 max_age_days）应在轮转成功后被 _purge_old_files 清掉
    stale_backup = log_file.with_name(log_file.name + ".5")
    stale_backup.write_text("stale", encoding="utf-8")
    ten_days_ago = log_file.stat().st_mtime - 10 * 86400
    os.utime(stale_backup, (ten_days_ago, ten_days_ago))

    logger = logging.getLogger("test_rollover_success")
    original_handlers = list(logger.handlers)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("x" * 200)
        handler.flush()

        assert log_file.with_name(log_file.name + ".1").exists()
        assert not stale_backup.exists()
        assert handler.stream is not None
        assert handler._rollover_retry_at == 0.0
    finally:
        logger.handlers = original_handlers
        logger.propagate = True
        handler.close()
