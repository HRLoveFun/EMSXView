"""阶段输入/输出模式注册表。

管理各阶段 Schema 的注册、查询和策略管理，以及阶段间契约兼容性检查。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import BaseModel

from DataPipeline.validation.contract_checker import ContractCheckResult, check_contract_compatibility
from DataPipeline.validation.enums import SchemaDirection, ValidationPolicy

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """阶段输入/输出模式注册表。

    提供 Schema 的注册、查询和策略管理能力。每个阶段的输入和输出 Schema
    被独立注册，支持为不同阶段设置不同的校验策略。

    用法::

        registry = SchemaRegistry()
        registry.register("S1", SchemaDirection.OUTPUT, RawFillsSchema, policy=RELAXED)
        registry.register("S2", SchemaDirection.INPUT, RawFillsSchema, policy=STRICT)
    """

    def __init__(self) -> None:
        # 内部存储: {stage_name: {SchemaDirection: (schema_class, policy)}}
        self._schemas: dict[str, dict[SchemaDirection, tuple[type[BaseModel], ValidationPolicy]]] = {}

    def register(
        self,
        stage_name: str,
        direction: SchemaDirection | str,
        schema: type[BaseModel],
        policy: ValidationPolicy = ValidationPolicy.STRICT,
    ) -> None:
        """注册一个阶段的输入或输出 Schema。

        Args:
            stage_name: 阶段名称（如 "S1", "S2"）
            direction: 模式方向（INPUT 或 OUTPUT，支持字符串 "input"/"output"）
            schema: Pydantic BaseModel 子类
            policy: 校验策略（默认 STRICT）
        """
        if isinstance(direction, str):
            direction = SchemaDirection(direction)
        if policy is not None and isinstance(policy, str):
            policy = ValidationPolicy(policy)
        if stage_name not in self._schemas:
            self._schemas[stage_name] = {}
        self._schemas[stage_name][direction] = (schema, policy)
        logger.debug(
            "注册 %s %s Schema: %s (策略=%s)",
            stage_name,
            direction.value,
            schema.__name__,
            policy.value,
        )

    def get_input_schema(self, stage_name: str) -> type[BaseModel] | None:
        """获取指定阶段的输入 Schema。

        Args:
            stage_name: 阶段名称

        Returns:
            Pydantic BaseModel 子类，未注册则返回 None
        """
        entry = self._schemas.get(stage_name, {}).get(SchemaDirection.INPUT)
        return entry[0] if entry else None

    def get_output_schema(self, stage_name: str) -> type[BaseModel] | None:
        """获取指定阶段的输出 Schema。

        Args:
            stage_name: 阶段名称

        Returns:
            Pydantic BaseModel 子类，未注册则返回 None
        """
        entry = self._schemas.get(stage_name, {}).get(SchemaDirection.OUTPUT)
        return entry[0] if entry else None

    def get_policy(self, stage_name: str) -> ValidationPolicy:
        """获取指定阶段的校验策略。

        优先返回输出策略（输出校验），其次返回输入策略。
        未注册的策略默认为 STRICT。

        Args:
            stage_name: 阶段名称

        Returns:
            ValidationPolicy 枚举值
        """
        stage_schemas = self._schemas.get(stage_name, {})
        output_entry = stage_schemas.get(SchemaDirection.OUTPUT)
        if output_entry:
            return output_entry[1]
        input_entry = stage_schemas.get(SchemaDirection.INPUT)
        if input_entry:
            return input_entry[1]
        return ValidationPolicy.STRICT

    def get_registered_stages(self) -> list[str]:
        """返回所有已注册的阶段名称列表"""
        return list(self._schemas.keys())

    def check_contract(
        self,
        upstream_stage: str,
        downstream_stage: str,
    ) -> ContractCheckResult:
        """检查上下游阶段之间的模式契约兼容性。

        委托给 contract_checker.check_contract_compatibility()。

        Args:
            upstream_stage: 上游阶段名称
            downstream_stage: 下游阶段名称

        Returns:
            ContractCheckResult: 兼容性检查结果

        Raises:
            ValueError: 如果任一阶段的输出/输入 Schema 未注册
        """
        upstream_schema = self.get_output_schema(upstream_stage)
        downstream_schema = self.get_input_schema(downstream_stage)

        if upstream_schema is None:
            raise ValueError(f"上游阶段 '{upstream_stage}' 的输出 Schema 未注册")
        if downstream_schema is None:
            raise ValueError(f"下游阶段 '{downstream_stage}' 的输入 Schema 未注册")

        return check_contract_compatibility(upstream_schema, downstream_schema)

    def check_all_contracts(self) -> list[tuple[str, str, ContractCheckResult]]:
        """检查所有相邻阶段之间的契约兼容性。

        按阶段名称排序后，对每对相邻阶段执行 check_contract()。

        Returns:
            list of (upstream_stage, downstream_stage, ContractCheckResult)
        """
        stages = sorted(self.get_registered_stages())
        results: list[tuple[str, str, ContractCheckResult]] = []

        for i in range(len(stages) - 1):
            upstream = stages[i]
            downstream = stages[i + 1]
            try:
                result = self.check_contract(upstream, downstream)
                results.append((upstream, downstream, result))
            except ValueError as e:
                logger.warning("契约检查失败 %s→%s: %s", upstream, downstream, e)
                from DataPipeline.validation.enums import ContractCompatibility as CC
                results.append(
                    (
                        upstream,
                        downstream,
                        ContractCheckResult(
                            compatibility=CC.INCOMPATIBLE,
                            issues=[str(e)],
                        ),
                    )
                )
        return results
