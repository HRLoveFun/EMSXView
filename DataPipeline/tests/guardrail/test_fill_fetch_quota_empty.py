"""空响应完整性判断单元测试（005-bloomberg-quota-pause）。

校验:
    1. 预期有数据（合法工作日）但从未成功拉取过 → 空响应判定为"应拉未拉"
       （额度受限），写 fetch_log.status='failed' 并置位暂停标记
    2. 该日期已有 fetched 记录 → 空响应维持 empty，不覆写成功
    3. 周末 / 未来日期 / 永久空缺 → 空响应维持 empty（不误判失败）
    4. 额度类 API 错误 (EMSXQuotaError) → 记录 failed + 置位暂停，不重试
    5. fetch_range_aggregated 置位后短路剩余日期
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from DataPipeline.acquisition.bloomberg_fill_fetcher import EMSXQuotaError
from DataPipeline.common.quota_pause import (
    clear_quota_pause,
    is_quota_paused,
    load_quota_pause,
    set_quota_pause,
)
from DataPipeline.ingestion.fill_fetch import FillFetch


def _make_fill_fetch(
    monkeypatch,
    *,
    fetch_log_stats=None,
    write_repo=True,
):
    """构造 FillFetch，mock 掉 repo 与 DB 访问（不触真实 DB）。"""
    ff = FillFetch.__new__(FillFetch)
    ff.data_dir = None

    read_repo = MagicMock()
    read_repo.get_fetch_log_stats.return_value = fetch_log_stats or []
    write_repo_mock = MagicMock()
    ff.raw_fill_read = read_repo
    ff.raw_fill_write = write_repo_mock if write_repo else None
    ff._known_hashes = {}
    ff.db = None

    # 隔离 quota_pause 文件，避免污染真实数据目录
    tmp_pause_file = None

    def _use_tmp_pause_file(path=None):
        nonlocal tmp_pause_file
        if path is not None:
            tmp_pause_file = path
        return tmp_pause_file

    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path", _use_tmp_pause_file
    )
    return ff, write_repo_mock


# ── 测试 1: 预期有数据但未拉取过 → 空响应 = 应拉未拉 (写 failed + 置位) ─────


def test_empty_response_on_unfetched_trading_day_marks_failed(monkeypatch, tmp_path):
    """合法工作日从未拉取过 → 空响应判定为额度受限，写 failed + 置位。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    # 一个已过去的工作日（非周末非未来）
    yesterday = date.today() - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    date_compact = yesterday.strftime("%Y%m%d")

    with patch.object(
        ff, "_is_expectable_trading_day", return_value=True
    ), patch.object(ff, "_has_fetched_record", return_value=False):
        assert ff._should_treat_empty_as_quota(date_compact) is True

    ff._record_quota_failure(date_compact, "fill_empty_response")
    write_repo.record_fetch_failed.assert_called_once()
    assert is_quota_paused(pause_file) is True
    rec = load_quota_pause(pause_file)
    assert rec["reason"] == "fill_empty_response"
    clear_quota_pause(pause_file)


def test_fetch_day_empty_unfetched_sets_success_false(monkeypatch, tmp_path):
    """fetch_day 空响应且应拉未拉 → success=False、error 非空、写 failed。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    yesterday = date.today() - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)

    # 空响应：mock client.fetch_fills 返回 []
    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls, patch.object(
        ff, "_should_treat_empty_as_quota", return_value=True
    ):
        mock_client = MagicMock()
        mock_client.fetch_fills.return_value = []
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = ff.fetch_day(yesterday)

    assert result["success"] is False
    assert "Quota" in (result.get("error") or "")
    assert is_quota_paused(pause_file) is True
    write_repo.record_fetch_failed.assert_called_once()
    clear_quota_pause(pause_file)


# ── 测试 2: 已 fetched → 空响应维持 empty ───────────────────────────────────


def test_empty_response_on_fetched_day_keeps_empty(monkeypatch):
    """已有 fetched 记录 → 空响应不判为额度受限，不写 failed。"""
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    # 直接验证判定函数：_has_fetched_record=True → 不判 quota
    with patch.object(ff, "_is_expectable_trading_day", return_value=True), \
         patch.object(ff, "_has_fetched_record", return_value=True):
        assert ff._should_treat_empty_as_quota("20260601") is False
    write_repo.record_fetch_failed.assert_not_called()


# ── 测试 3: 周末/未来/永久空缺 → 空响应维持 empty ───────────────────────────


def test_empty_response_on_non_trading_day_keeps_empty(monkeypatch):
    """非预期交易日 → 空响应不判为额度受限。"""
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    with patch.object(ff, "_is_expectable_trading_day", return_value=False), \
         patch.object(ff, "_has_fetched_record", return_value=False):
        assert ff._should_treat_empty_as_quota("20260606") is False
    write_repo.record_fetch_failed.assert_not_called()


def test_is_expectable_trading_day_weekend_and_future():
    """_is_expectable_trading_day 排除周末与未来日期。"""
    ff = FillFetch.__new__(FillFetch)
    # 周末 2026-08-22 (周六)
    assert ff._is_expectable_trading_day("20260822") is False
    # 未来日期
    future = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    assert ff._is_expectable_trading_day(future) is False


# ── 测试 4: 额度类 API 错误 → 记录 failed + 置位，不重试 ───────────────────


def test_fetch_day_quota_error_sets_failed(monkeypatch, tmp_path):
    """fetch_day 遇 EMSXQuotaError → success=False、写 failed、置位暂停。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    yesterday = date.today() - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = EMSXQuotaError("QUOTA_EXCEEDED - boom")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = ff.fetch_day(yesterday)

    assert result["success"] is False
    assert "quota" in (result.get("error") or "").lower()
    assert is_quota_paused(pause_file) is True
    # 不重试：fetch_fills 只被调用一次
    assert mock_client.fetch_fills.call_count == 1
    clear_quota_pause(pause_file)


# ── 测试 5: fetch_range_aggregated 置位时探测 + 恢复自愈 ─────────────────────


def test_fetch_range_aggregated_probe_recovers_when_quota_recovers(monkeypatch, tmp_path):
    """置位暂停但探测成功（额度恢复）→ 清除标记并继续正常拉取。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )
    set_quota_pause("fill_empty_response", file_path=pause_file)

    start = date.today() - timedelta(days=5)
    end = date.today()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        # 探测返回数据 → 表示额度恢复
        mock_client.fetch_fills.return_value = [{"OrderId": "1"}]
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(start, end)

    # 探测成功后清除标记，随后正常拉取各工作日
    assert not is_quota_paused(pause_file), "探测成功应清除暂停标记"
    assert summary["quota_paused"] is False
    assert mock_client.fetch_fills.call_count >= 1
    clear_quota_pause(pause_file)


def test_fetch_range_aggregated_probe_fails_stays_paused(monkeypatch, tmp_path):
    """置位暂停且探测仍失败（额度未恢复）→ 保持置位，短路剩余日期。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, write_repo = _make_fill_fetch(monkeypatch, fetch_log_stats=[])
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )
    set_quota_pause("fill_empty_response", file_path=pause_file)

    start = date.today() - timedelta(days=5)
    end = date.today()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        # 探测仍抛额度错误 → 保持暂停
        mock_client.fetch_fills.side_effect = EMSXQuotaError("QUOTA_EXCEEDED - still")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(start, end)

    # 探测失败 → 仍置位，无正常拉取（仅 1 次探测调用）
    assert is_quota_paused(pause_file) is True
    assert summary["quota_paused"] is True
    assert mock_client.fetch_fills.call_count == 1
    clear_quota_pause(pause_file)
