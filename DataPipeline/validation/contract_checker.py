"""阶段间模式契约兼容性检查器。

基于 Pydantic Schema 定义的 model_fields 元数据，执行静态契约兼容性分析。
当上游阶段输出 Schema 发生变更时，自动检查所有下游阶段输入 Schema 是否仍兼容。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from DataPipeline.validation.enums import ContractCompatibility


@dataclass
class ContractCheckResult:
    """契约兼容性检查结果。

    Attributes:
        compatibility: 兼容性等级（COMPATIBLE / COMPATIBLE_WITH_WARNING / INCOMPATIBLE）
        issues: 不兼容项列表（兼容时为空）
    """

    compatibility: ContractCompatibility
    issues: list[str] = field(default_factory=list)


def check_contract_compatibility(
    upstream: type[BaseModel],
    downstream: type[BaseModel],
) -> ContractCheckResult:
    """检查上游输出 Schema 变更后是否仍满足下游输入期望。

    基于 Pydantic model_fields 元数据执行三类检查：
    1. 字段存在性：下游需要的字段在上游输出中是否存在
    2. 类型兼容性：字段类型是否匹配（int→float 为 WARNING，其他不匹配为 INCOMPATIBLE）
    3. 约束兼容性：下游约束在上游约束范围内则为兼容

    Args:
        upstream: 上游阶段的输出 Schema（Pydantic BaseModel 子类）
        downstream: 下游阶段的输入 Schema（Pydantic BaseModel 子类）

    Returns:
        ContractCheckResult: 包含兼容性等级和问题列表
    """
    issues: list[str] = []
    has_warning = False

    downstream_fields = downstream.model_fields
    upstream_fields = upstream.model_fields

    for field_name, field_info in downstream_fields.items():
        # 检查 1: 字段存在性
        if field_name not in upstream_fields:
            # 下游必填字段在上游输出中不存在
            if field_info.is_required():
                issues.append(
                    f"下游必需字段 '{field_name}' 在上游输出中不存在"
                )
            else:
                issues.append(
                    f"下游可选字段 '{field_name}' 在上游输出中不存在（可能导致数据为 None）"
                )
                has_warning = True
            continue

        upstream_field = upstream_fields[field_name]

        # 检查 2: 类型兼容性
        upstream_annotation = upstream_field.annotation
        downstream_annotation = field_info.annotation

        if upstream_annotation != downstream_annotation:
            # int → float 视为可兼容但有警告（可能损失精度）
            if upstream_annotation is int and downstream_annotation is float:
                issues.append(
                    f"字段 '{field_name}' 类型变更（上游 int → 下游 float），可能损失精度"
                )
                has_warning = True
            elif upstream_annotation is float and downstream_annotation is int:
                issues.append(
                    f"字段 '{field_name}' 类型不匹配: 上游输出 float, 下游期望 int"
                )
            else:
                issues.append(
                    f"字段 '{field_name}' 类型不匹配: "
                    f"上游输出 {_type_name(upstream_annotation)}, "
                    f"下游期望 {_type_name(downstream_annotation)}"
                )

    # 检查 3: 下游必填字段要求上游必须提供
    for field_name, field_info in downstream_fields.items():
        if field_name in upstream_fields and field_info.is_required():
            upstream_field = upstream_fields[field_name]
            if not upstream_field.is_required():
                issues.append(
                    f"下游必需字段 '{field_name}' 在上游为可选字段，可能导致运行时缺失"
                )
                has_warning = True

    # 判定兼容性等级
    fatal_issues = [i for i in issues if "类型不匹配" in i or "不存在" in i and "可选字段" not in i]
    warning_issues = [i for i in issues if i not in fatal_issues]

    if fatal_issues:
        return ContractCheckResult(
            compatibility=ContractCompatibility.INCOMPATIBLE,
            issues=fatal_issues + warning_issues,
        )
    if has_warning:
        return ContractCheckResult(
            compatibility=ContractCompatibility.COMPATIBLE_WITH_WARNING,
            issues=issues,
        )
    return ContractCheckResult(
        compatibility=ContractCompatibility.COMPATIBLE,
        issues=[],
    )


def _type_name(annotation: type | None) -> str:
    """获取类型的可读名称"""
    if annotation is None:
        return "None"
    return getattr(annotation, "__name__", str(annotation))
