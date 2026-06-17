"""管道阶段 Pydantic 模式定义。

每个阶段有其独立的输入/输出模式，字段名 MUST 与
``DataPipeline/storage/schema/columns.py`` 中定义的列名一致。
"""

from DataPipeline.validation.schemas.attribution import AttributionSchema
from DataPipeline.validation.schemas.daily_metrics import DailyMetricsSchema
from DataPipeline.validation.schemas.fill_bdib import FillBdibSchema
from DataPipeline.validation.schemas.processed_fills import (
    AggregateFillsSchema,
    OrderLabelsSchema,
    ProcessedFillsSchema,
)
from DataPipeline.validation.schemas.raw_fills import RawFillsSchema
from DataPipeline.validation.schemas.regime import RegimeSchema

__all__ = [
    # S1/S2
    "RawFillsSchema",
    # S2/S3/S4
    "ProcessedFillsSchema",
    "AggregateFillsSchema",
    "OrderLabelsSchema",
    # S5
    "FillBdibSchema",
    # S7
    "DailyMetricsSchema",
    # S8/S9
    "RegimeSchema",
    # S10
    "AttributionSchema",
]
