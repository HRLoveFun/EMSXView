r"""EMSXView 只读数据访问层（010-extract-pipeline D3）。

EMSXView 自 010 起为**纯读取消费者**：数据库更新维护已迁往独立仓库
EMSXDataPipeline（唯一写入方，数据根 D:\db）。本包是 EMSXView 内
``import DataPipeline`` 的替代物——从 DataPipeline 只读路径裁剪而来：

- ``ConnectionManager``：仅提供 READ tier（sqlite3 URI mode=ro，文件系统级
  拒绝写；不隐式建库）；WRITE/admin 请求直接拒绝。
- ``Config``：数据目录（默认 ``D:\db``，``EMSXVIEW_DATA_DIR`` 可覆盖）与
  库名/表名常量——与独立仓库 ``DataPipeline.config`` 保持契约一致，
  由契约测试锁定。
- 读 repository / MarketStoreReader / exchange_tz 等只读工具随包提供。

契约：**任何新增的库/表/列变更必须同时改独立仓库并更新契约测试**。
"""

from data_access.config import (
    DB_FILL_BDIB,
    DB_FETCH_HISTORY,
    DB_RAW_BDIB,
    DB_RAW_FILLS,
    Config,
)
from data_access.common.exchange_tz import convert_ny_to_local
from data_access.storage.connection import (
    AccessTier,
    ConnectionManager,
    resolve_access_tier,
)
from data_access.storage.market_store import MarketStoreReader
from data_access.storage.repositories import (
    SqliteFillReadRepository,
    SqliteRawFillReadRepository,
)

__all__ = [
    "Config",
    "ConnectionManager",
    "AccessTier",
    "resolve_access_tier",
    "MarketStoreReader",
    "SqliteFillReadRepository",
    "SqliteRawFillReadRepository",
    "convert_ny_to_local",
    "DB_RAW_FILLS",
    "DB_RAW_BDIB",
    "DB_FILL_BDIB",
    "DB_FETCH_HISTORY",
]
