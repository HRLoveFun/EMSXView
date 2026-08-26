"""超时降级分窗口拉取单元测试（2026-08-24 日更失败修复）。

背景:
    20260820 raw fill 数据量过大，全天单次 GetFills 请求在 event 超时
    窗口（3 consecutive timeouts，约 90s 无事件）内无法完成流式返回，
    被误判为 "bbcomm may be unresponsive"，日更标记 failed。手动将全天
    拆为 6 个时间窗口（4h/窗口）后成功获取。本测试校验该降级机制已固化
    到数据获取流程:

    1. fetch_range_aggregated: 全天超时 → 自动拆 4h 窗口重试成功
    2. 窗口级超时 → 二分降级（4h → 2h → 1h）直至成功
    3. 降级至最小窗口仍超时 → 记 error day，summary.success=False
    4. EMSXQuotaError 不触发降级（额度错误直接上抛，仅调用一次）
    5. fetch_day: 全天超时 → 拆窗口重试成功（原有行为保持）
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from DataPipeline.acquisition.bloomberg_fill_fetcher import (
    EMSXQuotaError,
    EMSXRequestError,
)
from DataPipeline.common.quota_pause import clear_quota_pause, is_quota_paused
from DataPipeline.ingestion.fill_fetch import (
    FillFetch,
    MIN_SPLIT_WINDOW_SECONDS,
    SPLIT_WINDOW_HOURS,
)


def _make_fill_fetch(monkeypatch, *, fetch_log_stats=None):
    """构造 FillFetch，mock 掉 repo 与 DB 访问（不触真实 DB）。"""
    ff = FillFetch.__new__(FillFetch)
    ff.data_dir = None

    read_repo = MagicMock()
    read_repo.get_fetch_log_stats.return_value = fetch_log_stats or []
    write_repo_mock = MagicMock()
    # 默认不判重，让测试聚焦降级拉取行为本身
    write_repo_mock.check_fetch_duplicate.return_value = False
    write_repo_mock.upsert_raw_api_data.return_value = 1
    ff.raw_fill_read = read_repo
    ff.raw_fill_write = write_repo_mock
    ff._known_hashes = defaultdict(set)
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


def _past_weekday() -> date:
    """返回最近一个已过去的非周末日期。"""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


_TIMEOUT_MSG = "3 consecutive timeouts — bbcomm may be unresponsive"


# ── 测试 1: fetch_range_aggregated 全天超时 → 拆 4h 窗口成功 ───────────────


def test_range_aggregated_full_day_timeout_falls_back_to_windows(monkeypatch, tmp_path):
    """全天请求超时 → 自动降级为 6 个 4h 窗口拉取，日更不再失败。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, _ = _make_fill_fetch(monkeypatch)
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    target = _past_weekday()
    window_calls = []

    def fake_fetch(from_dt, to_dt):
        duration = (to_dt - from_dt).total_seconds()
        # 全天请求（> 4h）超时；窗口请求正常返回
        if duration > SPLIT_WINDOW_HOURS * 3600:
            raise EMSXRequestError(_TIMEOUT_MSG)
        window_calls.append((from_dt, to_dt))
        return [{"OrderId": f"{from_dt.hour:02d}{from_dt.minute:02d}"}]

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = fake_fetch
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(target, target)

    assert summary["success"] is True
    assert summary["days_error"] == 0
    assert summary["days_fetched"] == 1
    # 4h 窗口 × 6（00:00-04:00 … 20:00-23:59:59），全天共 1+6=7 次调用
    assert len(window_calls) == 6
    assert mock_client.fetch_fills.call_count == 7
    assert is_quota_paused(pause_file) is False


# ── 测试 2: 窗口级超时 → 二分降级 ──────────────────────────────────────────


def test_window_timeout_bisects_to_smaller_windows(monkeypatch, tmp_path):
    """单个 4h 窗口仍超时 → 二分降级（2h → 1h）直至成功。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, _ = _make_fill_fetch(monkeypatch)
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    target = _past_weekday()
    all_calls = []

    def fake_fetch(from_dt, to_dt):
        duration = (to_dt - from_dt).total_seconds()
        all_calls.append((from_dt, to_dt))
        if duration > SPLIT_WINDOW_HOURS * 3600:
            raise EMSXRequestError(_TIMEOUT_MSG)
        # 08:00 起的窗口持续超时（模拟极端数据量），二分到 1h 才成功
        if from_dt.hour == 8 and duration > 3600:
            raise EMSXRequestError(_TIMEOUT_MSG)
        return [{"OrderId": "ok"}]

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = fake_fetch
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(target, target)

    assert summary["success"] is True
    assert summary["days_error"] == 0
    durations = {(to_dt - from_dt).total_seconds() for from_dt, to_dt in all_calls}
    # 08:00-12:00 (4h) 超时 → 二分出 2h 子窗口；2h 仍超时 → 二分出 1h 子窗口
    assert 7200.0 in durations
    assert 3600.0 in durations


def test_bisect_stops_at_min_window_and_raises(monkeypatch):
    """二分降级有下限：窗口时长 ≤ MIN_SPLIT_WINDOW_SECONDS 时不再拆分，直接上抛。"""
    ff, _ = _make_fill_fetch(monkeypatch)
    client = MagicMock()
    client.fetch_fills.side_effect = EMSXRequestError(_TIMEOUT_MSG)

    from datetime import datetime

    ws = datetime(2026, 8, 20, 8, 0, 0)
    we = ws + timedelta(seconds=MIN_SPLIT_WINDOW_SECONDS)

    try:
        ff._fetch_window_with_bisect(client, ws, we)
        raised = False
    except EMSXRequestError:
        raised = True
    assert raised is True
    # 最小窗口只调用一次，不再二分
    assert client.fetch_fills.call_count == 1


# ── 测试 3: 降级到底仍超时 → 记 error day ──────────────────────────────────


def test_range_aggregated_persistent_timeout_marks_error(monkeypatch, tmp_path):
    """全天与所有窗口均持续超时 → 记 error day，summary.success=False。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, _ = _make_fill_fetch(monkeypatch)
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    target = _past_weekday()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = EMSXRequestError(_TIMEOUT_MSG)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(target, target)

    assert summary["success"] is False
    assert summary["days_error"] == 1
    assert summary["quota_paused"] is False


# ── 测试 4: EMSXQuotaError 不触发降级 ──────────────────────────────────────


def test_quota_error_does_not_trigger_split_fallback(monkeypatch, tmp_path):
    """额度类错误直接上抛置位暂停，不做窗口降级（全天仅调用一次）。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, _ = _make_fill_fetch(monkeypatch)
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    target = _past_weekday()

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = EMSXQuotaError("QUOTA_EXCEEDED")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        summary = ff.fetch_range_aggregated(target, target)

    assert summary["quota_paused"] is True
    assert summary["success"] is False
    # 全天请求抛额度错误后直接上抛，不拆窗口
    assert mock_client.fetch_fills.call_count == 1
    clear_quota_pause(pause_file)


# ── 测试 5: fetch_day 超时降级（原有行为保持）─────────────────────────────


def test_fetch_day_full_day_timeout_falls_back_to_windows(monkeypatch, tmp_path):
    """fetch_day 全天超时 → 拆 4h 窗口重试成功。"""
    pause_file = tmp_path / "quota_pause.json"
    ff, _ = _make_fill_fetch(monkeypatch)
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )

    target = _past_weekday()

    def fake_fetch(from_dt, to_dt):
        duration = (to_dt - from_dt).total_seconds()
        if duration > SPLIT_WINDOW_HOURS * 3600:
            raise EMSXRequestError(_TIMEOUT_MSG)
        return [{"OrderId": f"{from_dt.hour:02d}"}]

    with patch(
        "DataPipeline.ingestion.fill_fetch.BloombergFillFetcher"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_fills.side_effect = fake_fetch
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = ff.fetch_day(target)

    assert result["success"] is True
    assert result["rows_fetched"] > 0
    # 1 次全天 + 6 个窗口
    assert mock_client.fetch_fills.call_count == 7
