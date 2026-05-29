"""Configuration bridge — DI registry for DataPipeline Config.

Provides a dependency injection mechanism so that platform_data modules
can access DataPipeline's Config without importing it directly. Consumers
(like CostView/api/main.py, backend/api/main.py) register the concrete
Config class at startup.

Phase 4: Eliminates the CostView ↔ DataPipeline bidirectional dependency
by allowing DataPipeline modules to resolve config through this bridge.
"""

from __future__ import annotations

from typing import Any

from platform_data.contracts.protocols import ConfigProtocol

_config_registry: dict[str, type] = {}


def register_config_impl(config_class: type) -> None:
    """Register a ConfigProtocol-compatible configuration class.

    Called at startup by CostView or backend to inject the concrete
    DataPipeline Config class into the platform_data layer.

    Args:
        config_class: A class with ConfigProtocol-compatible attributes
                      (e.g., DataPipeline.config.Config).
    """
    _config_registry["default"] = config_class


def get_config() -> type:
    """Return the registered Config class.

    Returns the concrete Config class (e.g., DataPipeline.config.Config)
    registered via register_config_impl(). If no implementation is
    registered, falls back to lazy-importing DataPipeline.config.Config.

    Returns:
        A class with ConfigProtocol-compatible static attributes.
    """
    if "default" in _config_registry:
        return _config_registry["default"]

    # No implementation registered — caller must register Config before using
    # config-dependent features. CostView/api/main.py calls register_config_impl()
    # at startup for standalone mode; backend/api/main.py should do the same.
    raise RuntimeError(
        "No Config implementation registered. "
        "Ensure register_config_impl(Config) is called at application startup "
        "(e.g. from CostView/api/main.py:_setup_dependencies() or backend/api/main.py)."
    )


# Convenience: export the protocol type for type annotations
__all__ = ["register_config_impl", "get_config", "ConfigProtocol"]
