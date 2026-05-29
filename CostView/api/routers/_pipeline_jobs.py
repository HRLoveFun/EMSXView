"""Phase 7b: Re-export from merged platform_data.pipeline_jobs module.

The original ~540-line implementation has been extracted to
platform_data/pipeline_jobs.py to eliminate code duplication.
"""

from platform_data.pipeline_jobs import (  # noqa: F401
    PIPELINE_STAGES,
    get_job,
    list_jobs,
    trigger_pipeline,
)
