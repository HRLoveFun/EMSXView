"""057 DL-03 — 更新机制检查脚本纯函数测试（2026-10-21 用户补充要求）。

锁死 scripts/ops/check_exchange_session_registry.py 的判定逻辑：
- judge_fills_bounds / judge_bars_bounds：边界（含缓冲）内不标记、超界标记、空数据不标记；
- judge_out_of_session_ratio：阈值边界（等于不超、超过才标记、total=0 不标记）；
- check_half_day_coverage：年度覆盖提醒；
- check_registry_coverage / check_timezone_consistency / check_doc_samples：差集与一致场景。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]  # backend/api → backend → 仓库根（worktree 根）
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import SESSION_REGISTRY  # noqa: E402

_SCRIPTS = REPO_ROOT / "scripts" / "ops"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_exchange_session_registry import (  # noqa: E402
    check_doc_samples,
    check_half_day_coverage,
    check_registry_coverage,
    check_timezone_consistency,
    judge_bars_bounds,
    judge_fills_bounds,
    judge_out_of_session_ratio,
)

_US = SESSION_REGISTRY["US"]  # 09:30-16:00


class TestJudgeBounds:
    def test_within_bounds_no_problems(self):
        assert judge_fills_bounds(_US, "09:30:00", "16:00:00", buffer_min=15) == []
        assert judge_fills_bounds(_US, "09:20:00", "16:10:00", buffer_min=15) == []  # 缓冲内

    def test_out_of_bounds_flagged(self):
        problems = judge_fills_bounds(_US, "09:00:00", "16:30:00", buffer_min=15)
        assert len(problems) == 2
        assert any("早于开盘" in p for p in problems)
        assert any("晚于收盘" in p for p in problems)

    def test_empty_data_not_flagged(self):
        assert judge_fills_bounds(_US, None, None) == []
        assert judge_fills_bounds(_US, "", "") == []

    def test_bars_accepts_full_timestamp(self):
        assert judge_bars_bounds(_US, "2026-10-15 09:30:00", "2026-10-15 16:00:00") == []
        problems = judge_bars_bounds(_US, "2026-10-15 08:00:00", "2026-10-15 16:00:00")
        assert any("首根 bar" in p for p in problems)


class TestRatioThreshold:
    def test_threshold_boundary(self):
        assert judge_out_of_session_ratio(5, 1000, threshold=0.005) is False  # 等于不超
        assert judge_out_of_session_ratio(6, 1000, threshold=0.005) is True  # 超过才标记
        assert judge_out_of_session_ratio(1, 0) is False  # 缺数据 ≠ 不一致


class TestHalfDayCoverage:
    def test_missing_year_reminds(self):
        today = date(2028, 1, 10)  # 条目只到 2027
        problems = check_half_day_coverage(today)
        assert problems and "2028" in problems[0]

    def test_covered_years_pass(self):
        today = date(2026, 6, 1)
        assert check_half_day_coverage(today) == []


class TestStaticChecks:
    def test_coverage_consistent_with_registry(self):
        # 注册表与白名单一致时无问题（当前状态即一致）
        assert check_registry_coverage() == []

    def test_timezone_consistent(self):
        assert check_timezone_consistency() == []

    def test_doc_samples_consistent(self):
        assert check_doc_samples() == []
