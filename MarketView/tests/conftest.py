"""MarketView 路由测试的公共路径设置。

将 MarketView 目录与仓库根加入 sys.path，保证：
- `import config` / `from routers...` 按 standalone 服务的方式解析
- platform_data / DataPipeline（仓库根下的包）可导入
"""

from __future__ import annotations

import sys
from pathlib import Path

MV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MV_ROOT.parent

for _path in (str(MV_ROOT), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
