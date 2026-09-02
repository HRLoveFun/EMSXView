"""Config.DATA_DIR 默认外置与覆盖优先级测试 (009-external-data-store)。

覆盖点：
- 未设置 EMSXVIEW_DATA_DIR 时默认目录在项目外（~/EMSXViewData/data）；
- EMSXVIEW_DATA_DIR 显式设置时优先生效，全部 DB 路径跟随派生；
- 旧目录仍有 *.db 且走外置默认 → UserWarning 提示运行迁移脚本；
- 旧目录显式指回 / 已无 *.db 时不告警。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def config_module():
    """reload 后的 config 模块；测试结束后 reload 恢复真实环境状态。"""
    import DataPipeline.config as module

    yield module
    # monkeypatch 已还原环境变量；reload 让 DATA_DIR 等类属性回到真实值
    importlib.reload(module)


def test_default_data_dir_is_external(config_module, monkeypatch):
    """未设置环境变量时，默认数据目录外置于用户主目录（项目外）。"""
    monkeypatch.delenv("EMSXVIEW_DATA_DIR", raising=False)
    importlib.reload(config_module)

    expected = Path.home() / "EMSXViewData" / "data"
    assert config_module.Config.DATA_DIR == expected
    assert config_module.Config.DEFAULT_DATA_DIR == expected
    # 数据目录不落在项目仓库树内
    assert config_module.Config._PROJECT_ROOT not in config_module.Config.DATA_DIR.parents


def test_env_override_wins(config_module, monkeypatch, tmp_path):
    """EMSXVIEW_DATA_DIR 显式设置时优先生效，DB 路径全部跟随派生。"""
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("EMSXVIEW_DATA_DIR", str(custom))
    importlib.reload(config_module)

    assert config_module.Config.DATA_DIR == custom
    assert config_module.Config.RAW_FILLS_DB == custom / "raw_fills.db"
    assert config_module.Config.FILL_BDIB_DB == custom / "fill_bdib.db"
    assert config_module.Config.BDIB_PARQUET_DIR == custom / "market" / "bdib_10s"


def test_legacy_warning_when_legacy_dbs_exist(config_module, monkeypatch, tmp_path):
    """旧目录仍有 *.db 且当前走外置目录 → UserWarning 提示迁移。"""
    legacy = tmp_path / "legacy_data"
    legacy.mkdir()
    (legacy / "raw_fills.db").write_bytes(b"sqlite")
    monkeypatch.setattr(config_module.Config, "LEGACY_DATA_DIR", legacy)
    monkeypatch.setattr(config_module.Config, "DATA_DIR", tmp_path / "external_data")

    with pytest.warns(UserWarning, match="migrate_data_dir"):
        config_module._warn_legacy_data_dir()


def test_no_warning_when_data_dir_points_to_legacy(config_module, monkeypatch, tmp_path):
    """显式指回旧目录（DATA_DIR == LEGACY_DATA_DIR）→ 尊重选择，不告警。"""
    legacy = tmp_path / "legacy_data"
    legacy.mkdir()
    (legacy / "raw_fills.db").write_bytes(b"sqlite")
    monkeypatch.setattr(config_module.Config, "LEGACY_DATA_DIR", legacy)
    monkeypatch.setattr(config_module.Config, "DATA_DIR", legacy)

    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("error", UserWarning)
        config_module._warn_legacy_data_dir()


def test_no_warning_when_legacy_dir_empty(config_module, monkeypatch, tmp_path):
    """旧目录存在但已无 *.db（已迁移/清理）→ 不告警。"""
    legacy = tmp_path / "legacy_data"
    legacy.mkdir()
    monkeypatch.setattr(config_module.Config, "LEGACY_DATA_DIR", legacy)
    monkeypatch.setattr(config_module.Config, "DATA_DIR", tmp_path / "external_data")

    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("error", UserWarning)
        config_module._warn_legacy_data_dir()
