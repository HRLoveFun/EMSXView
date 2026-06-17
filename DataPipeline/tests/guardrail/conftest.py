"""管道护栏机制测试共享 Fixture。

提供 Mock FinancialPipeline、内存 SQLite 数据库连接、样例数据生成工具函数。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from DataPipeline.validation.enums import SeverityLevel, StageStatus, ViolationType
from DataPipeline.validation.violation import ValidationViolation


# ═══════════════════════════════════════════════════════════════════════════════
# Mock PipelineContext
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class MockPipelineContext:
    """简化的 PipelineContext，用于护栏单元测试"""

    target_dates: list[str] = field(default_factory=lambda: ["2026-01-15"])
    force: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    is_successful: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Mock BaseStage / FinancialPipeline
# ═══════════════════════════════════════════════════════════════════════════════


class MockStage:
    """模拟单个管道阶段，可控制执行行为和输出数据"""

    def __init__(
        self,
        name: str,
        should_succeed: bool = True,
        output_records: list[dict[str, Any]] | None = None,
        raise_exception: Exception | None = None,
    ) -> None:
        self._name = name
        self._should_succeed = should_succeed
        self._output_records = output_records or []
        self._raise_exception = raise_exception
        self.execute_called = False

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: MockPipelineContext) -> bool:
        self.execute_called = True
        if self._raise_exception:
            raise self._raise_exception
        if not self._should_succeed:
            return False
        return True

    def get_output(self) -> list[dict[str, Any]]:
        """返回阶段模拟输出数据"""
        return self._output_records


class MockFinancialPipeline:
    """模拟 FinancialPipeline，持有有序的 MockStage 列表"""

    def __init__(self, name: str = "Mock-Pipeline") -> None:
        self._name = name
        self.stages: list[MockStage] = []

    def add_stage(self, stage: MockStage) -> MockFinancialPipeline:
        self.stages.append(stage)
        return self

    def run(self, context: MockPipelineContext) -> MockPipelineContext:
        for stage in self.stages:
            result = stage.execute(context)
            context.summary[stage.name] = {"success": result}
            if not result:
                context.is_successful = False
                break
        return context


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite 内存数据库连接
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def memory_db() -> sqlite3.Connection:
    """创建内存 SQLite 数据库连接"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 样例数据生成工具
# ═══════════════════════════════════════════════════════════════════════════════

# 合法成交记录模板
_VALID_FILL_TEMPLATE: dict[str, Any] = {
    "FillId": 1,
    "OrderId": 100,
    "RouteId": 10,
    "FillPrice": 150.25,
    "FillShares": 100.0,
    "Amount": 15025.0,
    "RouteShares": 200.0,
    "Side": "BUY",
    "Exchange": "US",
    "ExecType": "TRD",
    "Ticker": "AAPL",
    "Broker": "BRK1",
    "StrategyType": "VWAP",
    "algo": "VWAP",
    "TraderName": "TraderA",
    "Currency": "USD",
    "SecurityName": "Apple Inc.",
    "LimitPrice": 150.0,
    "StopPrice": 0.0,
    "TraderUuid": "uuid-001",
    "LastCapacity": "A",
    "LastMarket": "NYSE",
    "Liquidity": "L",
    "LocalExchangeSymbol": "AAPL",
    "Account": "ACC01",
    "Type": "LIMIT",
    "NyOrderCreateAsOfDateTime": "2026-01-15T09:30:00",
    "NyTranCreateAsOfDateTime": "2026-01-15T10:00:00",
    "DateTimeOfFill": "2026-01-15T10:00:00",
    "order_as_of_date": "2026-01-15",
    "mkt_timestamp": "2026-01-15T10:00:00",
    "local_fill_datetime": "2026-01-15T10:00:00",
    "exchange_exec_time": "2026-01-15T10:00:00",
    "route_as_of_time": "2026-01-15T09:30:00",
    "is_closing_auction": 0,
    "region": "US",
    "equ_ticker": "AAPL US",
    "ccy_ticker": "USD",
}


def generate_valid_fill_record(override: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成一条合法的完整成交记录"""
    record = dict(_VALID_FILL_TEMPLATE)
    if override:
        record.update(override)
    return record


def generate_valid_fill_records(count: int) -> list[dict[str, Any]]:
    """生成多条合法成交记录（FillId 递增）"""
    records: list[dict[str, Any]] = []
    for i in range(count):
        rec = dict(_VALID_FILL_TEMPLATE)
        rec["FillId"] = i + 1
        rec["OrderId"] = 100 + i
        rec["RouteId"] = 10 + i
        records.append(rec)
    return records


def load_fixture_json(filename: str) -> list[dict[str, Any]]:
    """从 tests/fixtures/ 目录加载 JSON 测试数据"""
    fixture_path = Path(__file__).parent.parent / "fixtures" / filename
    if not fixture_path.exists():
        return []
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# 常用测试 Fixture
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def valid_fill_records() -> list[dict[str, Any]]:
    """10 条合法成交记录"""
    return generate_valid_fill_records(10)


@pytest.fixture
def missing_field_record() -> dict[str, Any]:
    """缺失 FillPrice 字段的记录"""
    rec = generate_valid_fill_record()
    del rec["FillPrice"]
    return rec


@pytest.fixture
def out_of_range_record() -> dict[str, Any]:
    """FillShares 为负、FillPrice 为零的记录"""
    return generate_valid_fill_record({"FillShares": -100.0, "FillPrice": 0.0})


@pytest.fixture
def sample_violation() -> ValidationViolation:
    """示例违规记录（用于日志/熔断测试）"""
    return ValidationViolation(
        run_id="20260616-000000-test00",
        stage_name="S2",
        field_name="FillPrice",
        expected_constraint="type=float, ge=0",
        actual_value=-1.0,
        severity=SeverityLevel.ERROR,
        violation_type=ViolationType.RANGE_VIOLATION,
        record_identifier="FillId=999",
    )
