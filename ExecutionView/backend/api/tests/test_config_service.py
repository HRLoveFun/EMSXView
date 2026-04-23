"""Tests for ConfigService — versioning, freshness, and persistence."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from services.config_service import ConfigService
from schemas import BrokerAlgorithmConfig, StrategyConfig, StrategyParameter


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_config(broker: str = "BMTB") -> BrokerAlgorithmConfig:
    return BrokerAlgorithmConfig(
        broker=broker,
        exchange="US",
        strategies=[
            StrategyConfig(
                name="VWAP",
                parameters=[
                    StrategyParameter(
                        fieldName="StartTime",
                        stringValue="09:30",
                        disable="N",
                        dataType="string",
                        description="Start time",
                    )
                ],
            )
        ],
    )


class TestConfigService:
    """Test ConfigService read/write/status."""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock()
        storage.get_configs = AsyncMock(return_value=[])
        storage.get_last_updated = AsyncMock(return_value=None)
        storage.needs_refresh = AsyncMock(return_value=True)
        storage.save = AsyncMock(return_value=True)
        return storage

    @pytest.fixture
    def svc(self, mock_storage):
        return ConfigService(mock_storage)

    def test_get_configs_empty(self, svc):
        result = _run(svc.get_configs())
        assert result == []

    def test_get_configs_returns_stored(self, svc, mock_storage):
        cfg = _make_config()
        mock_storage.get_configs.return_value = [cfg]
        result = _run(svc.get_configs())
        assert len(result) == 1
        assert result[0].broker == "BMTB"

    def test_needs_refresh_true_when_no_data(self, svc):
        assert _run(svc.needs_refresh()) is True

    def test_needs_refresh_false_when_fresh(self, svc, mock_storage):
        mock_storage.needs_refresh.return_value = False
        assert _run(svc.needs_refresh()) is False

    def test_version_hash_none_when_empty(self, svc):
        assert _run(svc.get_version_hash()) is None

    def test_version_hash_deterministic(self, svc, mock_storage):
        cfg = _make_config()
        mock_storage.get_configs.return_value = [cfg]
        h1 = _run(svc.get_version_hash())
        h2 = _run(svc.get_version_hash())
        assert h1 is not None
        assert h1 == h2

    def test_version_hash_changes_with_data(self, svc, mock_storage):
        cfg1 = _make_config("BMTB")
        mock_storage.get_configs.return_value = [cfg1]
        h1 = _run(svc.get_version_hash())

        cfg2 = _make_config("GS")
        mock_storage.get_configs.return_value = [cfg2]
        h2 = _run(svc.get_version_hash())

        assert h1 != h2

    def test_save_configs_delegates(self, svc, mock_storage):
        cfg = _make_config()
        result = _run(svc.save_configs([cfg]))
        assert result is True
        mock_storage.save.assert_awaited_once()

    def test_status_summary_no_data(self, svc):
        summary = _run(svc.status_summary())
        assert summary["hasData"] is False
        assert summary["needsRefresh"] is True
        assert summary["lastUpdated"] is None

    def test_status_summary_with_data(self, svc, mock_storage):
        now = datetime.now()
        mock_storage.get_last_updated.return_value = now
        mock_storage.needs_refresh.return_value = False
        mock_storage.get_configs.return_value = [_make_config()]
        summary = _run(svc.status_summary())
        assert summary["hasData"] is True
        assert summary["needsRefresh"] is False
        assert summary["version"] is not None
