"""日更静默失败回归测试（2026-08-21 修复）。

背景：database 页面触发 Update 后，fill fetch 阶段失败（Bloomberg
bbcomm 超时 / quota 暂停短路）不会传导到 run_daily_pipeline 的最终
status —— BDIB 等后续阶段正常完成后总状态仍为 success，前端显示
绿色 completed，而 fill 数据实际缺失（静默失败）。

修复点:
    1. daily_update._fetch_failure_detail: 从 fetch 摘要提取失败描述
    2. run_daily_pipeline: fetch 失败 → 最终 status=failed（exit 1 传导
       pipeline_jobs / 前端），但后续阶段仍继续执行（fail-soft，处理存量数据）
    3. fill_fetch.fetch_range_aggregated: quota 短路（probe 失败跳过全部
       日期）时 summary.success=False（此前恒为 error_days == 0 即 True）
"""

from __future__ import annotations

import importlib.util
import io
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from DataPipeline.acquisition.bloomberg_fill_fetcher import EMSXQuotaError
from DataPipeline.common.quota_pause import clear_quota_pause, set_quota_pause
from DataPipeline.ingestion.fill_fetch import FillFetch

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DAILY_UPDATE_PATH = _PROJECT_ROOT / "CostView" / "scripts" / "daily_update.py"

_daily_update_module = None

_FAILED_FETCH_SUMMARY = {
    "start_date": "20260820",
    "end_date": "20260820",
    "scope": "TradingSystem (login-based)",
    "total_days": 1,
    "days_fetched": 0,
    "days_skipped": 0,
    "days_empty": 0,
    "days_error": 1,
    "total_rows": 0,
    "files": [],
    "success": False,
    "quota_paused": False,
}


def _load_daily_update():
    """以文件路径加载 daily_update.py（scripts 目录非包，无法常规 import）。

    模块级存在 stdout/stderr UTF-8 包装逻辑，在 pytest capture 下替换流对象
    会破坏 fd 生命周期 —— 加载期间用无 buffer 的 StringIO 顶替，使两个
    包装分支（reconfigure / TextIOWrapper）均不触发。
    """
    global _daily_update_module
    if _daily_update_module is not None:
        return _daily_update_module
    spec = importlib.util.spec_from_file_location(
        "daily_update_under_test", _DAILY_UPDATE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
    _daily_update_module = mod
    return mod


def _make_fill_fetch(*, fetch_log_stats=None):
    """构造 FillFetch，mock 掉 repo 与 DB 访问（不触真实 DB）。"""
    ff = FillFetch.__new__(FillFetch)
    ff.data_dir = None
    read_repo = MagicMock()
    read_repo.get_fetch_log_stats.return_value = fetch_log_stats or []
    write_repo = MagicMock()
    # MagicMock 默认 truthy 会让每天都被误判为 DB duplicate —— 显式返回 False
    write_repo.check_fetch_duplicate.return_value = False
    ff.raw_fill_read = read_repo
    ff.raw_fill_write = write_repo
    # _record_hash_in_memory 依赖 defaultdict(set) 的自动建键行为
    ff._known_hashes = defaultdict(set)
    ff.db = None
    return ff


def _patch_pipeline_stages(monkeypatch, mod, fetcher, pipeline_result=None):
    """mock run_daily_pipeline 的全部外部副作用（Bloomberg / DB / 报告 / 归档）。"""
    run_incremental_mock = MagicMock(
        return_value=pipeline_result or {"processing": {"rows_processed": 0}}
    )
    monkeypatch.setattr(
        "DataPipeline.ingestion.fill_fetch.FillFetch", lambda *a, **k: fetcher
    )
    monkeypatch.setattr(
        "DataPipeline.orchestration.core.run_incremental", run_incremental_mock
    )
    monkeypatch.setattr(
        "DataPipeline.analysis.downstream_interface.write_manifest", lambda: None
    )
    monkeypatch.setattr(mod, "_checkpoint_wal", lambda: None)
    monkeypatch.setattr(mod, "_run_archive_step", lambda: None)
    monkeypatch.setattr(mod, "_run_b4_observation_step", lambda: None)
    return run_incremental_mock


# ── 修复点 1: _fetch_failure_detail 判定逻辑 ───────────────────────────────


def test_fetch_failure_detail_error_days():
    """存在 error_days → 返回包含日期范围与错误天数的描述。"""
    mod = _load_daily_update()
    detail = mod._fetch_failure_detail(dict(_FAILED_FETCH_SUMMARY))
    assert detail is not None
    assert "1 day(s) errored" in detail
    assert "20260820" in detail


def test_fetch_failure_detail_quota_paused_only():
    """quota 暂停短路（旧语义 success=True + quota_paused=True）也要报失败。"""
    mod = _load_daily_update()
    detail = mod._fetch_failure_detail({
        "start_date": "20260820", "end_date": "20260820",
        "days_error": 0, "quota_paused": True, "success": True,
    })
    assert detail is not None
    assert "quota paused" in detail


def test_fetch_failure_detail_success_and_up_to_date():
    """成功 / up-to-date / 非 dict 输入 → 无失败。"""
    mod = _load_daily_update()
    assert mod._fetch_failure_detail({
        "start_date": "20260820", "end_date": "20260820",
        "days_error": 0, "quota_paused": False, "success": True,
    }) is None
    assert mod._fetch_failure_detail({"status": "up-to-date"}) is None
    assert mod._fetch_failure_detail(None) is None


# ── 修复点 2: run_daily_pipeline 失败传导 ──────────────────────────────────


def test_run_daily_pipeline_marks_failed_when_fetch_errors(monkeypatch):
    """fill fetch 失败 → 最终 status=failed 且 error 非空（静默失败修复核心）。"""
    mod = _load_daily_update()
    fetcher = MagicMock()
    fetcher.determine_fetch_range.return_value = (date(2026, 8, 20), date(2026, 8, 20))
    fetcher.fetch_range_aggregated.return_value = dict(_FAILED_FETCH_SUMMARY)

    run_incremental_mock = _patch_pipeline_stages(monkeypatch, mod, fetcher)

    summary = mod.run_daily_pipeline(generate_report=False)

    assert summary["status"] == "failed"
    assert summary["error"] and "Fill fetch failed" in summary["error"]
    # fail-soft：后续 processing / BDIB 阶段仍继续执行（处理存量数据）
    assert run_incremental_mock.called


def test_run_daily_pipeline_marks_failed_when_quota_shortcircuit(monkeypatch):
    """quota 短路（跳过全部日期）→ 最终 status=failed。"""
    mod = _load_daily_update()
    fetcher = MagicMock()
    fetcher.determine_fetch_range.return_value = (date(2026, 8, 20), date(2026, 8, 20))
    fetcher.fetch_range_aggregated.return_value = {
        "start_date": "20260820", "end_date": "20260820",
        "days_fetched": 0, "days_error": 0, "total_rows": 0,
        "success": False, "quota_paused": True,
    }

    _patch_pipeline_stages(monkeypatch, mod, fetcher)

    summary = mod.run_daily_pipeline(generate_report=False)

    assert summary["status"] == "failed"
    assert "quota paused" in (summary.get("error") or "")


def test_run_daily_pipeline_success_when_fetch_ok(monkeypatch):
    """fetch 成功 → status=success（回归对照，不受修复影响）。"""
    mod = _load_daily_update()
    fetcher = MagicMock()
    fetcher.determine_fetch_range.return_value = (date(2026, 8, 20), date(2026, 8, 20))
    fetcher.fetch_range_aggregated.return_value = {
        "start_date": "20260820", "end_date": "20260820",
        "days_fetched": 1, "days_error": 0, "total_rows": 42,
        "success": True, "quota_paused": False,
    }

    _patch_pipeline_stages(
        monkeypatch, mod, fetcher,
        pipeline_result={"processing": {"rows_processed": 42}},
    )

    summary = mod.run_daily_pipeline(
        generate_report=False,
        freshness_check=lambda: None,
        exchange_audit=lambda: {"outside_whitelist": [], "whitelisted_no_data": []},
    )
    assert summary["status"] == "success"
    assert summary["exchange_diff"] == {"outside_whitelist": [], "whitelisted_no_data": []}


# ── 修复点 3: fetch_range_aggregated quota 短路 success 语义 ───────────────


def test_quota_shortcircuit_marks_summary_failed(monkeypatch, tmp_path):
    """quota 置位 + probe 失败短路全部日期 → summary.success 必须为 False。"""
    pause_file = tmp_path / "quota_pause.json"
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )
    set_quota_pause("fill_empty_response", file_path=pause_file)

    ff = _make_fill_fetch(fetch_log_stats=[])
    start = date.today() - timedelta(days=5)
    end = date.today()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = EMSXQuotaError("QUOTA_EXCEEDED")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(start, end)

    assert summary["quota_paused"] is True
    # 修复点：短路时 success 不能伪装成功（此前 error_days==0 → True）
    assert summary["success"] is False
    clear_quota_pause(pause_file)


def test_quota_probe_success_keeps_summary_success(monkeypatch, tmp_path):
    """quota 置位但探测成功（额度恢复）→ 正常拉取，success=True。"""
    pause_file = tmp_path / "quota_pause.json"
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )
    set_quota_pause("fill_empty_response", file_path=pause_file)

    ff = _make_fill_fetch(fetch_log_stats=[])
    start = date.today() - timedelta(days=5)
    end = date.today()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.return_value = [{"OrderId": "1"}]
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(start, end)

    assert summary["quota_paused"] is False
    assert summary["success"] is True
    clear_quota_pause(pause_file)


# ═══════════════ 场景 4: 阶段短路归因传导（M1.2 / 事故 A3, 2026-08-26） ═══════════════


def test_stage_failure_detail_extracts_short_circuit_reason():
    """bdib summary 携带 short_circuit_reason 时必须被提取为失败描述。"""
    mod = _load_daily_update()
    detail = mod._stage_failure_detail({
        "bdib": {
            "completed": True, "dates": 2,
            "raw_bdib_rows": 0, "fill_bdib_rows": 0,
            "short_circuit_reason": "ticker_exchange_map 为空",
        },
    })
    assert detail is not None
    assert "short-circuited" in detail
    assert "ticker_exchange_map" in detail


def test_stage_failure_detail_none_for_normal_pipeline():
    """无 short_circuit_reason / 非 dict 输入时返回 None（不误报）。"""
    mod = _load_daily_update()
    assert mod._stage_failure_detail({"bdib": {"completed": True, "raw_bdib_rows": 123}}) is None
    assert mod._stage_failure_detail({"processing": {"rows_processed": 42}}) is None
    assert mod._stage_failure_detail(None) is None


def test_run_daily_pipeline_marks_failed_when_bdib_short_circuits(monkeypatch):
    """事故 A3 回归锁定：BDIB 短路时日更最终状态必须是 failed 而非绿色 success。"""
    mod = _load_daily_update()
    fetcher = MagicMock()
    fetcher.determine_fetch_range.return_value = (date(2026, 8, 20), date(2026, 8, 20))
    fetcher.fetch_range_aggregated.return_value = {
        "start_date": "20260820", "end_date": "20260820",
        "days_fetched": 1, "days_error": 0, "total_rows": 42,
        "success": True, "quota_paused": False,
    }

    _patch_pipeline_stages(
        monkeypatch, mod, fetcher,
        pipeline_result={
            "processing": {"rows_processed": 42},
            "bdib": {
                "completed": True, "dates": 2, "raw_bdib_rows": 0,
                "processed_raw_bdib_rows": 0, "fill_bdib_rows": 0,
                "short_circuit_reason": (
                    "get_ticker_exchange_map 返回空 — ticker_repository 中无匹配 "
                    "BDIB_EXCHANGE 白名单的记录"
                ),
            },
        },
    )

    summary = mod.run_daily_pipeline(generate_report=False)

    assert summary["status"] == "failed"
    assert summary["error"] and "short-circuited" in summary["error"]


def _prev_bday(d: date) -> date:
    """回退到前一个工作日（剔除周末）。"""
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d


def test_freshness_ok_when_recent():
    """M2.2：各库最新交易日新鲜时返回 None（不误报）。"""
    mod = _load_daily_update()
    today = date.today().strftime("%Y%m%d")
    assert mod._freshness_failure_detail(max_dates={
        "raw_fills": today, "processed_fills": today,
        "raw_bdib": today, "fill_bdib": today,
    }) is None


def test_freshness_fails_when_stale():
    """M2.2：缺失超过 FAIL 交易日必须失败（事故 A3 类静默停更 2 交易日）。"""
    mod = _load_daily_update()
    # 缺失 2 个交易日的库必须触发失败（FRESHNESS_FAIL_BUSINESS_DAYS=2）
    d0 = date.today()
    stale = _prev_bday(_prev_bday(d0)).strftime("%Y%m%d")
    detail = mod._freshness_failure_detail(max_dates={
        "raw_fills": d0.strftime("%Y%m%d"), "processed_fills": d0.strftime("%Y%m%d"),
        "raw_bdib": stale, "fill_bdib": stale,
    })
    assert detail is not None
    assert "新鲜度校验失败" in detail
    assert "raw_bdib=" in detail


def test_freshness_warn_only_within_threshold():
    """M2.2：缺失 1 个交易日（WARN 窗口）仅告警不失败（容忍长周末）。"""
    mod = _load_daily_update()
    # 仅缺失 1 个交易日（如周一跑批数据到上周五）属正常，不触发失败
    d0 = date.today()
    prev = _prev_bday(d0).strftime("%Y%m%d")
    assert mod._freshness_failure_detail(max_dates={
        "raw_fills": d0.strftime("%Y%m%d"), "processed_fills": d0.strftime("%Y%m%d"),
        "raw_bdib": prev, "fill_bdib": prev,
    }) is None


def test_freshness_business_day_helper():
    """M2.2：_business_days_between 正确计入工作日、剔除周末。"""
    mod = _load_daily_update()
    # 周五(2026-08-21) 到 下周一(2026-08-24) 含端点计 2 个工作日（Fri+Mon）
    assert mod._business_days_between(date(2026, 8, 21), date(2026, 8, 24)) == 2


def test_freshness_missing_db_skipped():
    """M2.2：库缺失/未填充（None）不误判为失败。"""
    mod = _load_daily_update()
    assert mod._freshness_failure_detail(max_dates={
        "raw_fills": None, "processed_fills": None,
        "raw_bdib": None, "fill_bdib": None,
    }) is None


def test_stage_failure_generalized_to_any_stage():
    """M1.4：short_circuit_reason 判定推广至任意阶段（非仅 bdib）。"""
    mod = _load_daily_update()
    fake = {"route_metrics": {"short_circuit_reason": "空候选日期"}}
    detail = mod._stage_failure_detail(fake)
    assert detail is not None
    assert "route_metrics stage short-circuited" in detail
    assert "空候选日期" in detail


def test_stage_failure_nested_short_circuit():
    """M1.4：嵌套子字典中的 short_circuit_reason 也能递归捕获。"""
    mod = _load_daily_update()
    fake = {"bdib": {"inner": {"short_circuit_reason": "映射为空"}}}
    detail = mod._stage_failure_detail(fake)
    assert detail is not None
    assert "映射为空" in detail


def test_stage_failure_absent_when_clean():
    """M1.4：无 short_circuit_reason 的阶段 summary 返回 None。"""
    mod = _load_daily_update()
    assert mod._stage_failure_detail({"bdib": {"completed": True}, "route_metrics": {"completed": True}}) is None


def test_exchange_audit_detects_outside_whitelist():
    """M3.2：数据有但白名单遗漏的交易所必须被审计出来（B1 类漂移）。"""
    mod = _load_daily_update()
    import DataPipeline.pipeline_guards.exchange_whitelist_audit as aud
    whitelist = set(aud.Config.BDIB_EXCHANGE)
    actual = whitelist | {"NEWEX"}  # NEWEX 出现于数据但不在白名单
    diff = aud.audit_exchange_coverage(actual_exchanges=actual)
    assert "NEWEX" in diff["outside_whitelist"]
    assert diff["whitelisted_no_data"] == sorted(whitelist - actual)


def test_exchange_audit_clean_when_matched():
    """M3.2：白名单与实际分布一致时无漂移。"""
    mod = _load_daily_update()
    import DataPipeline.pipeline_guards.exchange_whitelist_audit as aud
    whitelist = set(aud.Config.BDIB_EXCHANGE)
    diff = aud.audit_exchange_coverage(actual_exchanges=set(whitelist))
    assert diff["outside_whitelist"] == []

