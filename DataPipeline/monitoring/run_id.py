"""运行 ID 生成器。

为每次管道执行生成唯一标识，格式为 YYYYMMDD-HHMMSS-xxxxxx（6 位随机字符）。
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone


def generate_run_id() -> str:
    """生成唯一的管道运行 ID。

    格式: YYYYMMDD-HHMMSS-xxxxxx
    - 前 8 位: 日期 (YYYYMMDD)
    - 中间 6 位: 时间 (HHMMSS)
    - 后缀 6 位: 随机字符

    Returns:
        格式为 "20260616-153000-a1b2c3" 的唯一 ID

    Examples:
        >>> rid = generate_run_id()
        >>> len(rid) == 21
        True
        >>> rid[8] == '-'
        True
        >>> rid[15] == '-'
        True
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    random_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{date_part}-{time_part}-{random_part}"
