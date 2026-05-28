"""Broker algorithm configuration schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List
from pydantic import BaseModel, Field


class StrategyParameter(BaseModel):
    """Strategy parameter configuration."""

    fieldName: str
    stringValue: str
    disable: str
    dataType: str = "string"
    description: str = ""


class StrategyConfig(BaseModel):
    """Strategy configuration for a broker."""

    name: str
    parameters: List[StrategyParameter]


class BrokerAlgorithmConfig(BaseModel):
    """Broker algorithm configuration."""

    broker: str
    strategies: List[StrategyConfig]


class BrokerAlgorithmStorage(BaseModel):
    """Storage wrapper for broker algorithm data."""

    version: str = "1.0"
    lastUpdated: str = Field(default_factory=lambda: datetime.now().isoformat())
    configs: List[BrokerAlgorithmConfig]
