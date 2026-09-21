"""评估治理元数据 —— 026 阶段三（B4 治理层）。

依据 B4 评价矩阵的治理层（`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md:119`）：

> 版本锁定、数据血缘、基准冻结、压力测试、漂移监测、人工停机和实盘小规模验证

本模块提供**随结果附带**的治理元数据，使每次评估都能自证「按哪个基准、哪一版口径、
什么样本、哪些降级」得出的 —— 这是「可审计」与「黑箱分数」的分界。

**口径不可默认**（plan §5.2 DP-3-3，依据 D1）：基准必须显式传入，服务端不设默认值；
缺失即报错。D1 的原文是「而不是事后挑选最有利基准」，默认值会让这条约束形同虚设。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

#: 基准冻结必须随结果返回的键（缺任一即视为治理不完整）
REQUIRED_METADATA_KEYS: tuple[str, ...] = (
    "benchmark", "spec_version", "data_range", "scope", "sample_sizes",
)


def evaluation_metadata(
    *,
    benchmark: str,
    spec_version: str,
    data_range: tuple[str, str],
    scope: Any,
    sample_sizes: Mapping[str, int],
    degradations: Optional[Sequence[str]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """组装评估结果的治理元数据（版本锁 / 基准冻结 / 数据血缘 / 降级披露）。

    Args:
        benchmark: 本次比较所用基准（**必须显式给出**，无默认值）。
        spec_version: 评估口径版本（与 `report_spec.SPEC_VERSION` 同源）。
        data_range: 数据期 ``(start, end)``。
        scope: 报告作用域 payload（`report_measure.ReportScope.to_payload()`）。
        sample_sizes: 各比较组的样本量（血缘：结论基于多少样本）。
        degradations: 本次涉及的降级说明（如环境变量不可得、代理口径回退）。
        extra: 其他需留痕的键值。

    Raises:
        ValueError: ``benchmark`` 为空（基准不可默认）。
    """
    if not benchmark or not str(benchmark).strip():
        raise ValueError(
            "benchmark 必须显式指定：D1 要求基准冻结，服务端不设默认值"
            "（避免事后挑选最有利基准）"
        )

    payload: dict[str, Any] = {
        "benchmark": str(benchmark).strip(),
        "spec_version": spec_version,
        "data_range": {"start_date": data_range[0], "end_date": data_range[1]},
        "scope": scope,
        "sample_sizes": dict(sample_sizes),
        "degradations": list(degradations or ()),
        # 版本锁定与漂移监测的锚点：归档时凭此判断两次结论是否同口径
        "governance_schema": "026-phase3",
    }
    if extra:
        payload.update(dict(extra))
    return payload


def missing_metadata_keys(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """返回缺失的必备治理键（供测试与端点前置校验）。"""
    return tuple(
        key for key in REQUIRED_METADATA_KEYS
        if not payload.get(key)
    )


def assert_governance_complete(payload: Mapping[str, Any]) -> None:
    """校验治理元数据完整性；缺项即抛错（不静默产出不可审计的结论）。

    Raises:
        ValueError: 存在缺失的必备键。
    """
    missing = missing_metadata_keys(payload)
    if missing:
        raise ValueError(f"治理元数据不完整，缺失：{', '.join(missing)}")
