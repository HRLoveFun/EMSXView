"""交易所会话注册表契约（057 DL-03）——纯数据，无 IO。

Ownership: platform_data 发布；Consumers: MarketView（DL-10/11/14）、ExecutionView
（DL-17/18）、CostView（DL-19）、管道侧调度（DL-08 触发，经契约镜像）。

口径来源：
- 收盘竞价时刻/ADJUST 集合：管道 `closing_auction_times` 与 `EXCHANGE_AUCTION_TIME_ADJUST`
  镜像（docs/EMSXDataPipeline-TECHNICAL_GUIDE.md §5.5 明文样本；完整 34 表在 DL-06 冻结）；
- 时段桶：管道 S9 `assign_time_bucket` 口径镜像（指南 §5.9：5 市场 US/AU/LN/EU/JP，
  JP 额外 lunch_break）；
- 市场码折叠：管道 `derive_market_code` 镜像（指南 §5.9：EUR→EU、MUMBAI 系→IN）；
- 会话时刻：公开市场规则；开盘竞价仅填高置信度市场，不确定留 None（见更新机制）。
"""

from __future__ import annotations

from dataclasses import dataclass

# 注册表版本：结构或数据变更时升版（语义同 INTENT_MAPPING_VERSION），
# 下游消费时记录所用版本；更新流程见 scripts/ops/check_exchange_session_registry.py
SESSION_REGISTRY_VERSION = "exch-session-v1"


@dataclass(frozen=True)
class ExchangeSession:
    """单个交易所的会话定义（时刻均为交易所本地挂钟时间 HH:MM）。

    lunch / opening_auction 可空；closing_auction 与 market_close 通常同值
    （管道口径：收盘竞价时刻即收盘时刻，如 US=16:00）。
    early_close_auction：收盘竞价提前开始（管道 ADJUST 集合）——判定成交
    归属收盘竞价时需 ±1min 容差，见指南 §5.5。
    """

    exchange_code: str
    timezone: str
    market_open: str
    market_close: str
    closing_auction: str
    early_close_auction: bool = False
    lunch: tuple[str, str] | None = None
    opening_auction: tuple[str, str] | None = None
    notes: str = ""


def _s(
    code: str,
    tz: str,
    open_: str,
    close: str,
    *,
    early: bool = False,
    lunch: tuple[str, str] | None = None,
    opening: tuple[str, str] | None = None,
    notes: str = "",
) -> ExchangeSession:
    return ExchangeSession(
        exchange_code=code,
        timezone=tz,
        market_open=open_,
        market_close=close,
        closing_auction=close,
        early_close_auction=early,
        lunch=lunch,
        opening_auction=opening,
        notes=notes,
    )


# ── 会话注册表（键 = Config.BDIB_EXCHANGE 白名单 26 市场）──────────────────────
# 时区与 data_access/common/exchange_tz.py::EXCHANGE_TIMEZONE 一致（xbbg 映射，
# FP/SM 映射 London、MK/SP 映射 Hong_Kong 是 xbbg 怪癖——挂钟时刻仍为本地时间，
# 测试锁双源一致）。
SESSION_REGISTRY: dict[str, ExchangeSession] = {
    "AU": _s("AU", "Australia/Sydney", "10:00", "16:00", notes="ASX 常规时段"),
    "AV": _s("AV", "Europe/Vienna", "09:00", "17:30", notes="Wiener Börse"),
    "BB": _s("BB", "Europe/Brussels", "09:00", "17:30", notes="Euronext Brussels"),
    # 2026-08-03 入白名单：Nth SSE-SEHK（沪港通），行情映射 CH，时段同 A 股
    "C1": _s("C1", "Asia/Shanghai", "09:30", "15:00", lunch=("11:30", "13:00"), notes="Nth SSE-SEHK（沪港通）"),
    "FH": _s("FH", "Europe/Helsinki", "10:00", "18:30", notes="Nasdaq Helsinki"),
    # xbbg 把 Paris 映射到 Europe/London；挂钟为巴黎本地
    "FP": _s("FP", "Europe/London", "09:00", "17:30", notes="Euronext Paris（xbbg tz 映射 London）"),
    "GA": _s("GA", "Europe/Athens", "10:00", "17:20", notes="ATHEX"),
    # Xetra 开盘竞价 08:50–09:00（高置信度）
    "GR": _s("GR", "Europe/Berlin", "09:00", "17:30", opening=("08:50", "09:00"), notes="Xetra/Frankfurt"),
    "HK": _s("HK", "Asia/Hong_Kong", "09:30", "16:00", lunch=("12:00", "13:00"), opening=("09:00", "09:30"), notes="HKEX"),
    # LSE 上市（都柏林）——开盘竞价 07:50–08:00
    "ID": _s("ID", "Europe/London", "08:00", "16:30", opening=("07:50", "08:00"), notes="LSE（Dublin 代码）"),
    "IJ": _s("IJ", "Asia/Jakarta", "09:00", "16:00", notes="IDX 常规时段"),
    "IM": _s("IM", "Europe/Rome", "09:00", "17:30", notes="Borsa Italiana"),
    # NSE/BSE 预开盘竞价 09:00–09:15（高置信度）
    "IN": _s("IN", "Asia/Calcutta", "09:15", "15:30", opening=("09:00", "09:15"), notes="NSE/BSE"),
    # TSE：竞价提前开始（ADJUST）——「exec_time+1min ≥ close」判定
    "JP": _s("JP", "Asia/Tokyo", "09:00", "15:30", early=True, lunch=("11:30", "12:30"), opening=("08:00", "09:00"), notes="TSE（午休 11:30–12:30）"),
    # KRX 开盘竞价 08:00–09:00（高置信度）
    "KS": _s("KS", "Asia/Seoul", "09:00", "15:30", opening=("08:00", "09:00"), notes="KRX"),
    "LN": _s("LN", "Europe/London", "08:00", "16:30", opening=("07:50", "08:00"), notes="LSE"),
    # xbbg 把 Malaysia 映射到 Asia/Hong_Kong；挂钟为吉隆坡本地
    "MK": _s("MK", "Asia/Hong_Kong", "09:00", "17:00", notes="Bursa Malaysia（xbbg tz 映射 HK）"),
    "NA": _s("NA", "Europe/Amsterdam", "09:00", "17:30", notes="Euronext Amsterdam"),
    "NO": _s("NO", "Europe/Oslo", "09:00", "16:30", notes="Oslo Børs"),
    "PL": _s("PL", "Europe/Lisbon", "08:00", "16:30", notes="Euronext Lisbon"),
    "SJ": _s("SJ", "Africa/Johannesburg", "09:00", "17:00", notes="JSE"),
    # xbbg 把 Madrid 映射到 Europe/London；挂钟为马德里本地
    "SM": _s("SM", "Europe/London", "09:00", "17:30", notes="Bolsa de Madrid（xbbg tz 映射 London）"),
    # xbbg 把 Singapore 映射到 Asia/Hong_Kong；挂钟为新加坡本地
    "SP": _s("SP", "Asia/Hong_Kong", "09:00", "17:00", lunch=("12:30", "13:30"), opening=("08:30", "09:00"), notes="SGX（午休 12:30–13:30）"),
    # Nasdaq Nordic Stockholm：收盘竞价提前开始（ADJUST）
    "SS": _s("SS", "Europe/Stockholm", "09:00", "17:30", early=True, notes="Nasdaq Nordic Stockholm"),
    "SW": _s("SW", "Europe/Zurich", "09:00", "17:30", notes="SIX Swiss Exchange"),
    # NYSE/NASDAQ：MOC/LOC 指示单 15:50 起可输入（ADJUST）
    "US": _s("US", "America/New_York", "09:30", "16:00", early=True, notes="NYSE/NASDAQ（MOC 竞价 15:50 起）"),
}

# 管道 EXCHANGE_AUCTION_TIME_ADJUST 集合镜像（指南 §5.5 明文；JP/PW/SS/BZ/CN/MM/US）
EARLY_CLOSE_AUCTION_EXCHANGES: frozenset[str] = frozenset({"JP", "PW", "SS", "BZ", "CN", "MM", "US"})

# 管道 S9 assign_time_bucket 启用市场（指南 §5.9；其余市场 None）
TIME_BUCKET_MARKETS: tuple[str, ...] = ("US", "AU", "LN", "EU", "JP")

# 管道 derive_market_code 折叠规则镜像（指南 §5.9：EUR→EU；MUMBAI/BOMBAY/INDIA/NSE/BSE→IN；
# 无 Currency 时 11 个欧洲交易所折叠——收录欧洲大陆主要市场 → EU，泛 LSE 系 ID → LN）
MARKET_CODE_FOLDING: dict[str, str] = {
    "EUR": "EU",
    "MUMBAI": "IN",
    "BOMBAY": "IN",
    "INDIA": "IN",
    "NSE": "IN",
    "BSE": "IN",
    # 欧洲大陆市场折叠为 EU（S9 无 EU 会话条目，桶由各交易所自身时段派生）
    "AV": "EU", "BB": "EU", "FH": "EU", "GA": "EU", "GR": "EU", "IM": "EU",
    "NA": "EU", "NO": "EU", "PL": "EU", "SM": "EU", "SS": "EU", "SW": "EU", "FP": "EU",
    # 泛 LSE 系归 LN
    "ID": "LN",
}

# 静态半日市收盘覆盖表（tasks「先以本侧静态表起步」；完整假日日历与管道 P3 合为一份）。
# 键 = (exchange_code, "YYYY-MM-DD")，值 = 当日收盘 HH:MM。仅收录确定性规则条目，
# 每条有公开日历来源；年度轮换由检查脚本 check_half_day_coverage 提醒。
HALF_DAY_CLOSE_OVERRIDES: dict[tuple[str, str], str] = {
    # 美国：感恩节后一日 13:00（感恩节 = 11 月第 4 个星期四）
    ("US", "2026-11-27"): "13:00",
    ("US", "2027-11-26"): "13:00",
    # 英国/爱尔兰（LSE）：平安夜与除夕 13:30
    ("LN", "2026-12-24"): "13:30",
    ("LN", "2026-12-31"): "13:30",
    ("LN", "2027-12-24"): "13:30",
    ("LN", "2027-12-31"): "13:30",
    # 德国（Xetra）：平安夜与除夕 14:00
    ("GR", "2026-12-24"): "14:00",
    ("GR", "2026-12-31"): "14:00",
    ("GR", "2027-12-24"): "14:00",
    ("GR", "2027-12-31"): "14:00",
    # 香港（HKEX）：平安夜与除夕 12:00
    ("HK", "2026-12-24"): "12:00",
    ("HK", "2026-12-31"): "12:00",
    ("HK", "2027-12-24"): "12:00",
    ("HK", "2027-12-31"): "12:00",
}

# 管道 §5.5 明文样本（契约测试锁定，防镜像漂移）
PIPELINE_CLOSING_AUCTION_SAMPLES: dict[str, str] = {"US": "16:00", "JP": "15:30", "HK": "16:00"}
