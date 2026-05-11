"""Shared configuration and utility modules for the DataPipeline.

Each submodule is imported directly by consumers:
    from DataPipeline.src.common.processing_config import ProcessingConfig
    from DataPipeline.src.storage.schema.columns import EMSX_FILL_COLUMNS

This __init__.py intentionally does not re-export symbols —
consumers import from submodules directly.
"""
