# Plan: CostView æ•°æ®åº“å­ç³»ç»Ÿç‹¬ç«‹é‡æž„

> **åˆ†æ”¯**: `refactor/architecture`
> **æ—¥æœŸ**: 2026-05-07ï¼ˆåŽŸå§‹ï¼‰| 2026-05-07ï¼ˆv2 è¿­ä»£æ–¹æ¡ˆæ›´æ–°ï¼‰
> **çŠ¶æ€**: PLANï¼ˆå¾…æ‰¹å‡† â€” è¿­ä»£æ–¹æ¡ˆ v2ï¼‰
> **å…³è”æž¶æž„å†³ç­–**: ProcessedFillsDB God Object æ‹†åˆ† (2026-05-07)ã€CostView Pipeline Parallelization (2026-04-15)ã€Logical Data Domain Adapter Entry (2026-04-22)ã€Regime Layer Schema Conventions (2026-04-27)ã€DB Subsystem Phase 1-3 (2026-05-07)
> **é¢„è®¡æ€»å·¥æ—¶**: 5.5â€“6.5 å‘¨ï¼ˆ4 ä¸ªè¿­ä»£ä¸²è¡ŒæŽ¨è¿›ï¼‰

---

## 1. ç›®çš„ä¸Žé¢„æœŸç»“æžœ

### ç›®çš„

å°† CostView ä¸­æ•£å¸ƒåœ¨ 6 ä¸ª SQLite æ•°æ®åº“ã€3 ç§å¹¶å­˜è®¿é—®æ¨¡å¼ï¼ˆè£¸ SQL / DB ç±» / Repository Protocolï¼‰ä¸­çš„æ•°æ®èŒè´£ï¼Œç»Ÿä¸€ç‹¬ç«‹ä¸ºã€Œæ•°æ®åº“å­ç³»ç»Ÿã€ï¼Œå®žçŽ°ï¼š

1. **å•ä¸€æ•°æ®è®¿é—®å…¥å£** â€” æ¶ˆé™¤æ‰€æœ‰è£¸ `sqlite3.connect()` å’Œæ·±å±‚ DB ç±»ç›´æŽ¥å¯¼å…¥
2. **Protocol è§£è€¦** â€” ä¸šåŠ¡å±‚é›¶ sqlite3 ä¾èµ–ï¼Œæ‰€æœ‰è®¿é—®é€šè¿‡ Repository Protocol
3. **ç»Ÿä¸€ç”Ÿå‘½å‘¨æœŸç®¡ç†** â€” è¿žæŽ¥åˆ›å»ºã€å¤ç”¨ã€é‡Šæ”¾ç”± ConnectionManager ç»Ÿä¸€æŽ§åˆ¶
4. **è·¨æ¨¡å—åˆæ³•å…¥å£** â€” å¤–éƒ¨æ¨¡å—é€šè¿‡ `platform_data` é€‚é…å±‚è®¿é—®ï¼Œæ¶ˆé™¤æ·±å±‚å¯¼å…¥

### é¢„æœŸç»“æžœ

- CostView æ•°æ®å±‚æˆä¸ºå¯ç‹¬ç«‹æµ‹è¯•ã€å¯æ›¿æ¢å­˜å‚¨åŽç«¯çš„å­ç³»ç»Ÿ
- `pipeline.py` ä¸å†ç›´æŽ¥æŒæœ‰ 5 ä¸ª DB å®žä¾‹ï¼Œæ”¹ä¸ºæŒæœ‰ `CostViewDatabase` å•ä¾‹
- `ExecutionView` ä¸å†æ·±å±‚å¯¼å…¥ `CostView.src.*`ï¼ˆå·²é€šè¿‡ Phase 3 å®žçŽ°ï¼‰
- æ‰€æœ‰ .db æ–‡ä»¶çš„ schema ç‰ˆæœ¬é€šè¿‡ `MigrationManager` ç»Ÿä¸€ç®¡ç†
- `CostView/src/db/` ä¹‹å¤–é›¶ `sqlite3.connect()` è°ƒç”¨

### çº¦æŸæ¡ä»¶

1. **ä¸é‡å†™ï¼Œå¢žé‡é‡æž„** â€” æ¯ä¸ªè¿­ä»£ç»“æŸåŽç³»ç»Ÿå¿…é¡»å¯è¿è¡Œã€æµ‹è¯•å…¨é€šè¿‡
2. **å‘åŽå…¼å®¹** â€” æ—§çš„ DB ç±»é€šè¿‡ Facade ä¿æŒå¯ç”¨ï¼Œç›´åˆ°è¿­ä»£ 4 å†æ·»åŠ  deprecation warning
3. **ä¸é™ä½Žæ€§èƒ½** â€” Repository æŠ½è±¡å±‚å¼•å…¥çš„å¼€é”€å¿…é¡» < 1%ï¼ˆæ–¹æ³•è°ƒç”¨ ~1Î¼s vs SQLite æŸ¥è¯¢ ~100Î¼s+ï¼‰
4. **è·¨æ¨¡å—æ•°æ®è®¿é—®é€šè¿‡å…±äº«é€‚é…å±‚** â€” ç¬¦åˆ .github/agent.md æ°¸ä¹…æ€§çº¦æŸ

---

## 2. å½“å‰è¿›åº¦ï¼šPhase 1-3 åŸºç¡€è®¾æ–½å·²å®Œæˆ

### 2.1 å·²å®Œæˆå·¥ä½œ

| Phase | äº§å‡º | çŠ¶æ€ |
|---|---|---|
| Phase 1 | `db/connection.py`ï¼ˆConnectionManager + AccessTierï¼‰ã€`db/protocols.py`ï¼ˆ12 ä¸ª Protocolï¼‰ã€`db/dto.py`ã€`database_access.py` â†’ re-export | âœ… å·²å®Œæˆ |
| Phase 2 | `db/repositories/`ï¼ˆ10 ä¸ªå®žçŽ°ï¼‰ã€`db/schema/columns.py`ã€`db/schema/migrations/manager.py`ã€`db/facade.py`ï¼ˆCostViewDatabaseï¼‰ | âœ… å·²å®Œæˆ |
| Phase 3 | `platform_data/contracts/`ã€`CostViewDatabaseAdapter`ã€`SCORECARD_COHORTS` è¿ç§»ã€`platform_data/repositories.py` è§£é™¤ ProcessingConfig ä¾èµ– | âœ… å·²å®Œæˆ |

### 2.2 æœªå®Œæˆå·¥ä½œï¼šè°ƒç”¨æ–¹è¿ç§»ä¸¥é‡æ»žåŽ

**æ ¸å¿ƒçŸ›ç›¾**ï¼šæ–°æŠ½è±¡å±‚å·²å»ºå¥½ï¼Œä½†ä¸»æµä¸šåŠ¡ä»£ç ä»åœ¨èµ°æ—§è·¯å¾„ã€‚åŒå±‚å¹¶å­˜å¢žåŠ äº†ç†è§£å’Œç»´æŠ¤æˆæœ¬ã€‚

| æŒ‡æ ‡ | å½“å‰å€¼ | ç›®æ ‡å€¼ |
|---|---|---|
| `pipeline.py` ä¸­æ—§ DB ç±»å®žä¾‹åŒ– | 0ï¼ˆâœ… è¿­ä»£1å®Œæˆï¼‰ | 0 |
| `CostView/src/` ä¸­è£¸ `sqlite3.connect()` | 0ï¼ˆâœ… è¿­ä»£3å®Œæˆï¼Œä»… `db/connection.py` å†…éƒ¨ä¿ç•™ï¼‰ | 0 |
| `platform_data/adapters.py` å¯¹ CostView æ·±å±‚å¯¼å…¥ | 1 å¤„ | 0 |
| `tca_query_service.py` ä¸­è£¸ SQL è¿žæŽ¥ | 0ï¼ˆâœ… è¿­ä»£2å®Œæˆï¼‰ | 0 |
| `execution_history_service.py` ä¸­è£¸ SQL è¿žæŽ¥ | 0ï¼ˆâœ… è¿­ä»£2å®Œæˆï¼‰ | 0 |
| `daily_metrics_calculator.py` ä¸­è£¸ SQL è¿žæŽ¥ | 0ï¼ˆâœ… è¿­ä»£2å®Œæˆï¼‰ | 0 |
| `MigrationManager.ensure_current()` å¯¹æ—§ DB ç±»ä¾èµ– | 0ï¼ˆâœ… è¿­ä»£3å®Œæˆï¼‰ | 0 |

### 2.3 å…­ä¸ª SQLite æ•°æ®åº“çš„ä¾èµ–æ‹“æ‰‘ï¼ˆä¸å˜ï¼‰

```
raw_fills.db (2.64GB)  â”€â”€fill_ingestionâ”€â”€â†’  processed_fills.db (14.84GB)
                                                  â”‚
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
                    â†“                              â†“
raw_bdib.db (68.98GB) â”€â”€processâ”€â”€â†’ processed_raw_bdib.db â”€â”€integrateâ”€â”€â†’ fill_bdib.db (41MB)
                                                  â”‚
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                    â†“
              regime.db (4.57GB)  â†â”€â”€ attribution/regime tagger
```

---

## 3. å…³é”®å› ç´ åˆ†æžï¼ˆè¡¥å……æ·±åº¦ï¼‰

### 3.1 æ•°æ®ä¸€è‡´æ€§

**é£Žé™©ç­‰çº§ï¼šé«˜**

| åœºæ™¯ | å½“å‰è¡Œä¸º | ç‹¬ç«‹åŽé£Žé™© | ç¼“è§£ç­–ç•¥ |
|---|---|---|---|
| è·¨ db åŽŸå­å†™å…¥ | æ— ä¿éšœï¼ˆæ¯ä¸ª .db ç‹¬ç«‹äº‹åŠ¡ï¼‰ | ä¸å˜ï¼Œéœ€æ˜¾å¼å£°æ˜Ž | å•åº“å†…äº‹åŠ¡å®‰å…¨ + processing_log å¹‚ç­‰æ ‡è®° |
| Schema ç‰ˆæœ¬ | regime.db æœ‰è¿ç§»ï¼›å…¶ä»–é ä»£ç ä¸­ ALTER | éœ€ç»Ÿä¸€è¿ç§»ç®¡ç† | `MigrationManager.ensure_current()` ç»Ÿä¸€è¿½è¸ª |
| å¹¶å‘å†™å…¥ | æ¯çº¿ç¨‹åˆ›å»ºç‹¬ç«‹ DB å®žä¾‹ | éœ€è¿žæŽ¥æ± æˆ–ä¼šè¯ç®¡ç† | `ConnectionManager` çº¿ç¨‹æœ¬åœ°ç¼“å­˜ + WAL + busy_timeout |
| æ•°æ®å›žæ»š | æ— è·¨ db å›žæ»š | éœ€è¡¥å¿äº‹åŠ¡ | pipeline é˜¶æ®µçº§é‡è¯• + processing_log status çŠ¶æ€æœº |

**å†³ç­–**ï¼šæ•°æ®åº“å­ç³»ç»Ÿä¸æä¾›è·¨ .db çš„äº‹åŠ¡ä¿è¯ï¼ˆSQLite å¤©ç„¶ä¸æ”¯æŒï¼‰ï¼Œä½†æä¾›ï¼š
- å• .db å†…çš„äº‹åŠ¡å®‰å…¨ï¼ˆWAL + busy_timeout + æ˜¾å¼äº‹åŠ¡è¾¹ç•Œï¼‰
- è¡¥å¿äº‹åŠ¡æ¨¡å¼ï¼ˆpipeline é˜¶æ®µçº§é‡è¯• + processing_log å¹‚ç­‰æ ‡è®°ï¼‰
- **å¢žå¼º**ï¼šprocessing_log å¢žåŠ  `status` å­—æ®µï¼ˆ`in_progress` / `completed` / `failed`ï¼‰ï¼Œæ›¿ä»£å½“å‰å¸ƒå°”å¹‚ç­‰æ£€æŸ¥
- Schema ç‰ˆæœ¬ç»Ÿä¸€è¿½è¸ª

### 3.2 æŽ¥å£è®¾è®¡

Phase 1-2 å·²å®šä¹‰çš„ Protocol ä½“ç³»è®¾è®¡åˆç†ï¼Œä½†éœ€è¡¥å……ï¼š

**è¡¥å…… 1ï¼šConnectionManager çº¿ç¨‹æœ¬åœ°è¿žæŽ¥ç¼“å­˜**

é«˜é¢‘æŸ¥è¯¢åœºæ™¯ï¼ˆå¦‚ regime tagger é€è¡Œæ ‡ç­¾æŸ¥è¯¢ï¼‰ä¸‹ï¼Œæ¯æ¬¡ `get_connection()` åˆ›å»ºæ–°è¿žæŽ¥ä¼šç´¯ç§¯å¼€é”€ï¼š

```python
class ConnectionManager:
    def __init__(self, config=None):
        ...
        self._thread_local = threading.local()

    def get_connection(self, database, tier=None):
        """ä¼˜å…ˆå¤ç”¨åŒçº¿ç¨‹åŒåº“è¿žæŽ¥ï¼Œé¿å…é«˜é¢‘åˆ›å»ºã€‚"""
        key = f"{database}_{resolve_access_tier(tier).value}"
        cache = getattr(self._thread_local, 'connections', {})
        if key in cache:
            conn = cache[key]
            try:
                conn.execute("SELECT 1")  # è¿žæŽ¥å­˜æ´»æ£€æŸ¥
                return conn
            except Exception:
                cache.pop(key, None)
        conn = self._create_connection(...)
        cache[key] = conn
        self._thread_local.connections = cache
        return conn
```

**è¡¥å…… 2ï¼šQueryBuilder ç‹¬ç«‹æ¨¡å—åŒ–**

`tca_query_service.py` 60KB çš„æŸ¥è¯¢é€»è¾‘ä¸å¼ºåˆ¶æ‹†è§£ï¼Œè€Œæ˜¯é€šè¿‡ `FillQueryBuilder` ä¿æŒçµæ´»æ€§ï¼š

```python
# db/query_builder.pyï¼ˆæ–°å¢žï¼‰
class FillQueryBuilder:
    """å¤æ‚åˆ†æžæŸ¥è¯¢çš„é€ƒç”Ÿèˆ±å£ã€‚"""
    def __init__(self, connection_manager: ConnectionManager):
        self._mgr = connection_manager
        self._filters: List[Tuple[str, Any]] = []

    def for_date_range(self, start: str, end: str) -> Self: ...
    def with_ticker(self, ticker: str) -> Self: ...
    def with_side(self, side: str) -> Self: ...
    def with_broker(self, broker: str) -> Self: ...

    def execute_on(self, database: str) -> pd.DataFrame:
        """åœ¨æŒ‡å®šæ•°æ®åº“ä¸Šæ‰§è¡Œæž„å»ºçš„æŸ¥è¯¢ã€‚"""
        conn = self._mgr.get_connection(database, AccessTier.READ)
        try:
            sql, params = self._build_query()
            return pd.read_sql_query(sql, conn.raw_connection, params=params)
        finally:
            conn.close()
```

**è¡¥å…… 3ï¼šPipelineContext åŒæ¨¡å¼æ¶ˆé™¤ç­–ç•¥**

```python
@dataclass
class PipelineContext:
    connection_manager: Optional[ConnectionManager] = None
    _db: Optional[CostViewDatabase] = None

    @property
    def db(self) -> CostViewDatabase:
        """ç»Ÿä¸€çš„æ•°æ®åº“è®¿é—®å…¥å£ã€‚"""
        if self._db is None:
            self._db = CostViewDatabase(self.get_connection_manager())
        return self._db

    # å‘åŽå…¼å®¹å±žæ€§ï¼ˆé€æ­¥åºŸå¼ƒï¼Œæ·»åŠ  deprecation warningï¼‰
    @property
    def raw_db(self) -> RawFillsDB:
        """DEPRECATED: Use db.raw_fills_read / db.raw_fills_write."""
        warnings.warn("Use context.db.raw_fills_read/write instead", DeprecationWarning, stacklevel=2)
        ...
```

### 3.3 æ€§èƒ½å½±å“

| æ“ä½œ | å½“å‰è·¯å¾„ | æŠ½è±¡å±‚è·¯å¾„ | é¢å¤–å¼€é”€ | å½±å“ |
|---|---|---|---|---|
| å•è¡Œè¯»å– | `conn.execute(sql)` | `repo.get_fill(id)` â†’ `conn.execute(sql)` | ~1Î¼s æ–¹æ³•è°ƒç”¨ | å¯å¿½ç•¥ |
| æ‰¹é‡å†™å…¥ 1000 è¡Œ | `conn.executemany()` | `repo.upsert(dtoList)` â†’ è½¬æ¢ + executemany | ~5ms è½¬æ¢ | å¯æŽ¥å— |
| DataFrame æŸ¥è¯¢ | `pd.read_sql_query()` | `repo.get_fills_for_date()` â†’ å†…éƒ¨ `pd.read_sql_query` | æ—  | æ— å½±å“ |
| tca å¤æ‚æŸ¥è¯¢ | 5 ä¸ªç§æœ‰è¿žæŽ¥å·¥åŽ‚ | `ConnectionManager` + `QueryBuilder` | ~2Î¼s è¿žæŽ¥èŽ·å– | å¯å¿½ç•¥ |
| é«˜é¢‘çŸ­æŸ¥è¯¢ï¼ˆregime taggerï¼‰ | è¿žæŽ¥å¤ç”¨ | æ— ç¼“å­˜ï¼šæ¯æ¬¡æ–°å»º | ~50Î¼s Ã— N | éœ€ç¼“å­˜ |

### 3.4 è§£è€¦ç­–ç•¥

ä¸‰å±‚æ¸è¿›å¼è§£è€¦ï¼š

1. **ç¬¬ä¸€å±‚ï¼šå†…éƒ¨ç»Ÿä¸€**ï¼ˆè¿­ä»£ 1-2ï¼‰â€” `pipeline.py` â†’ `CostViewDatabase`ï¼Œ`tca_query_service` â†’ `ConnectionManager`
2. **ç¬¬äºŒå±‚ï¼šè¾¹ç•Œå¯†å°**ï¼ˆè¿­ä»£ 3ï¼‰â€” `CostView/src/db/` ä¹‹å¤–é›¶è£¸ SQL
3. **ç¬¬ä¸‰å±‚ï¼šå¤–éƒ¨éš”ç¦»**ï¼ˆè¿­ä»£ 4ï¼‰â€” `platform_data` é›¶ CostView æ·±å±‚å¯¼å…¥ï¼Œæ—§ DB ç±»æ·»åŠ  deprecation warning

---

## 4. å®žæ–½è®¡åˆ’ï¼šå››è¿­ä»£æ¸è¿›å¼è¿ç§»

> **å…³é”®å˜æ›´**ï¼šåŽŸ Phase 1-3 çš„åŸºç¡€è®¾æ–½å·²å…¨éƒ¨å»ºæˆã€‚æœ¬è®¡åˆ’èšç„¦äºŽ**è°ƒç”¨æ–¹è¿ç§»**ï¼Œ
> å°† 32 å¤„æ—§è°ƒç”¨ç‚¹é€ä¸€è¿ç§»åˆ°æ–°æŠ½è±¡å±‚ã€‚æ¯ä¸ªè¿­ä»£ç‹¬ç«‹å¯éªŒè¯ã€‚

---

### è¿­ä»£ 1ï¼šPipeline è¿ç§»åˆ° CostViewDatabase

**ç›®æ ‡**ï¼š`pipeline.py` ä¸å†ç›´æŽ¥å®žä¾‹åŒ–æ—§ DB ç±»ï¼ˆ32 å¤„ â†’ 0ï¼‰ã€‚

**é¢„è®¡å·¥æ—¶**ï¼š1.5 å‘¨

#### æ­¥éª¤æ¸…å•

| # | æ­¥éª¤ | å˜æ›´æ–‡ä»¶ | é£Žé™© | æµ‹è¯•ç­–ç•¥ |
|---|---|---|---|---|
| 1.1 | `PipelineContext` å¢žåŠ  `db: CostViewDatabase` å±žæ€§ï¼ˆæ‡’åˆå§‹åŒ–ï¼‰ï¼Œä¿ç•™æ—§å­—æ®µå¹¶æ ‡è®° `@deprecated` | `pipeline.py` | ä½Ž | å•å…ƒæµ‹è¯• |
| 1.2 | `IngestStage` æ”¹ç”¨ `context.db.raw_fills_write` + `context.db.fills_write` | `pipeline.py`, `fill_ingestion.py` | ä¸­ | ingest å›žå½’ |
| 1.3 | `ProcessStage` æ”¹ç”¨ `context.db.fills_read` + `context.db.fills_write` | `pipeline.py` | ä¸­ | process å›žå½’ |
| 1.4 | `BDIBStage` æ”¹ç”¨ `context.db.market_data_write` | `pipeline.py` | ä¸­ | BDIB å›žå½’ |
| 1.5 | `IntegrateStage` æ”¹ç”¨ `context.db.integrated_write` | `pipeline.py` | ä¸­ | integrate å›žå½’ |
| 1.6 | `AggregateStage` æ”¹ç”¨ `context.db.fills_read` + `context.db.fills_write` | `pipeline.py` | ä¸­ | aggregate å›žå½’ |
| 1.7 | `fill_ingestion.py` ä¸­çš„ `RawFillsDB()` / `ProcessedFillsDB()` å®žä¾‹åŒ–æ”¹ä¸º Repository | `fill_ingestion.py` | ä¸­ | ingest å›žå½’ |
| 1.8 | `fill_fetch.py` ä¸­çš„ `RawFillsDB()` / `ProcessedFillsDB()` å®žä¾‹åŒ–æ”¹ä¸º Repository | `fill_fetch.py` | ä¸­ | fetch å›žå½’ |

#### è¿­ä»£ 1 éªŒæ”¶æ ‡å‡†

- [x] `pipeline.py` ä¸­é›¶ `RawFillsDB()` / `ProcessedFillsDB()` / `RawBDIBDB()` / `ProcessedRawBDIBDB()` / `FillBDIBDB()` å®žä¾‹åŒ–
- [x] `fill_ingestion.py` ä¸­é›¶æ—§ DB ç±»å®žä¾‹åŒ–
- [x] `fill_fetch.py` ä¸­é›¶æ—§ DB ç±»å®žä¾‹åŒ–
- [x] Pipeline å®Œæ•´è¿è¡Œæ— å›žå½’ï¼ˆå¯¼å…¥éªŒè¯é€šè¿‡ + 15/17 æµ‹è¯•é€šè¿‡ï¼‰
- [x] æ‰€æœ‰çŽ°æœ‰æµ‹è¯•é€šè¿‡ï¼ˆ2 ä¸ªé¢„å…ˆå­˜åœ¨çš„å¤±è´¥ä¸Žæœ¬æ¬¡å˜æ›´æ— å…³ï¼‰

---

### è¿­ä»£ 2ï¼štca_query_service è¿ç§»åˆ° ConnectionManager âœ… å·²å®Œæˆ

**ç›®æ ‡**ï¼šæ¶ˆé™¤ `tca_query_service.py` ä¸­çš„ 5 å¤„è£¸ `sqlite3.connect()`ã€‚

**é¢„è®¡å·¥æ—¶**ï¼š2 å‘¨ â†’ å®žé™… 1 å¤©

#### æ­¥éª¤æ¸…å•

| # | æ­¥éª¤ | å˜æ›´æ–‡ä»¶ | é£Žé™© | æµ‹è¯•ç­–ç•¥ |
|---|---|---|---|---|
| 2.1 | `ConnectionManager` å¢žå¼º `row_factory` å’Œ `path_overrides` å‚æ•° | `db/connection.py` | ä½Ž | è¿žæŽ¥æµ‹è¯• | âœ… |
| 2.2 | `TcaQueryService.__init__` æŽ¥å— `ConnectionManager` å‚æ•°ï¼ˆä¿ç•™ `db_path` å‘åŽå…¼å®¹ï¼Œå†…éƒ¨è½¬æ¢ `path_overrides`ï¼‰ | `tca_query_service.py` | ä½Ž | æž„é€ æµ‹è¯• | âœ… |
| 2.3 | 4 ä¸ª `_xxx_conn()` å·¥åŽ‚æ–¹æ³•æ”¹ç”¨ `ConnectionManager.get_connection()` | `tca_query_service.py` | ä¸­ | è¿žæŽ¥æµ‹è¯• | âœ… |
| 2.4 | `_compute_route_metrics_from_raw_bdib` ç±»åž‹æ³¨è§£æ›´æ–° | `tca_query_service.py` | ä½Ž | TCA æŠ¥å‘Šå›žå½’ | âœ… |
| 2.5 | `execution_history_service.py` æ³¨å…¥ `ConnectionManager` | `execution_history_service.py` | ä¸­ | åŽ†å²æŸ¥è¯¢å›žå½’ | âœ… |
| 2.6 | `daily_metrics_calculator.py` æ³¨å…¥ `ConnectionManager` | `daily_metrics_calculator.py` | ä¸­ | Stage 7 å›žå½’ | âœ… |

#### è¿­ä»£ 2 éªŒæ”¶æ ‡å‡†

- [x] `tca_query_service.py` ä¸­é›¶ `sqlite3.connect()` è°ƒç”¨
- [x] `execution_history_service.py` ä¸­é›¶ `sqlite3.connect()` è°ƒç”¨
- [x] `daily_metrics_calculator.py` ä¸­é›¶ `sqlite3.connect()` è°ƒç”¨
- [x] TCA æµ‹è¯•å¥—ä»¶ 42/42 é€šè¿‡
- [x] Pipeline å®ˆå«æµ‹è¯• 15/17 é€šè¿‡ï¼ˆ2 ä¸ªé¢„å…ˆå­˜åœ¨çš„å¤±è´¥ä¸Žæœ¬æ¬¡å˜æ›´æ— å…³ï¼‰

---

### è¿­ä»£ 3ï¼šæ—§ DB ç±»å†…éƒ¨è¿ç§» + è¾…åŠ©æ–‡ä»¶æ¸…ç† âœ… å·²å®Œæˆ

**ç›®æ ‡**ï¼šæ‰€æœ‰æ—§ DB ç±»å†…éƒ¨æ”¹ç”¨ `ConnectionManager`ï¼Œæ¶ˆé™¤è¾…åŠ©æ–‡ä»¶ä¸­çš„è£¸ SQLã€‚

**é¢„è®¡å·¥æ—¶**ï¼š1 å‘¨ â†’ å®žé™… 2 å¤©

#### æ­¥éª¤æ¸…å•

| # | æ­¥éª¤ | å˜æ›´æ–‡ä»¶ | é£Žé™© | æµ‹è¯•ç­–ç•¥ |
|---|---|---|---|---|
| 3.1 | `RawFillsDB` å†…éƒ¨ `_get_conn()` â†’ `ConnectionManager.get_connection("raw_fills")` | `raw_fills_db.py` | ä¸­ | åŽŸæœ‰ RawFillsDB æµ‹è¯• | âœ… |
| 3.2 | `RawBDIBDB` åŒä¸Š | `raw_bdib_db.py` | ä¸­ | åŒä¸Š | âœ… |
| 3.3 | `FillBDIBDB` åŒä¸Š | `fill_bdib_db.py` | ä¸­ | åŒä¸Š | âœ… |
| 3.4 | `ProcessedRawBDIBDB` åŒä¸Š | `processed_raw_bdib_db.py` | ä¸­ | åŒä¸Š | âœ… |
| 3.5 | `processed_fills_db/_base.py` çš„ `_get_conn()` â†’ `ConnectionManager` | `processed_fills_db/_base.py` | ä¸­ | ProcessedFillsDB æµ‹è¯• | âœ… |
| 3.6 | `validate_raw_fills.py`ã€`query_cli.py` æ”¹ç”¨ ConnectionManager | `validate_raw_fills.py`, `query_cli.py` | ä½Ž | è„šæœ¬åŠŸèƒ½éªŒè¯ | âœ… |
| 3.7 | regime æ¨¡å—å…¨é¢è¿ç§»è‡³ ConnectionManager + ä¿®å¤ run_journal æ˜¾å¼ commit | `regime/schema.py`, `regime/migrations/apply.py`, `regime/fill_regime_tagger.py`, `regime/run_journal.py` | ä¸­ | regime pipeline å›žå½’ | âœ… |
| 3.8 | `attribution/repositories.py` SqliteFillRepository + SqliteBarDataRepository æ³¨å…¥ ConnectionManager | `attribution/repositories.py` | ä¸­ | attribution æµ‹è¯• | âœ… |
| 3.9 | `MigrationManager._ensure_inline_schema()` ä½¿ç”¨ `db/schema/inline_ddl.py` ç‹¬ç«‹ DDL å‡½æ•°ï¼Œä¸å†ä¾èµ–æ—§ DB ç±» | `db/schema/inline_ddl.py` (æ–°å¢ž), `db/schema/migrations/manager.py` | ä¸­ | è¿ç§»æµ‹è¯• | âœ… |

#### è¿­ä»£ 3 éªŒæ”¶æ ‡å‡†

- [x] `CostView/src/db/` ä¹‹å¤–é›¶ `sqlite3.connect()` è°ƒç”¨
- [x] æ‰€æœ‰æ—§ DB ç±»å†…éƒ¨ä½¿ç”¨ `ConnectionManager`
- [x] `MigrationManager` ä¸å†ä¾èµ–æ—§ DB ç±»è¿›è¡Œ schema åˆå§‹åŒ–
- [x] Pipeline å®Œæ•´è¿è¡Œæ— å›žå½’
- [x] æ‰€æœ‰çŽ°æœ‰æµ‹è¯•é€šè¿‡ï¼ˆ81/81ï¼‰

---

### è¿­ä»£ 4ï¼šç§»é™¤æ—§å±‚ + å¯†å°è¾¹ç•Œ

**ç›®æ ‡**ï¼šCostView å†…éƒ¨é›¶è£¸ SQLï¼Œplatform_data é›¶ CostView æ·±å±‚å¯¼å…¥ï¼Œæ—§ DB ç±»æ ‡è®°åºŸå¼ƒã€‚

**é¢„è®¡å·¥æ—¶**ï¼š1 å‘¨

#### æ­¥éª¤æ¸…å•

| # | æ­¥éª¤ | å˜æ›´æ–‡ä»¶ | é£Žé™© | æµ‹è¯•ç­–ç•¥ |
|---|---|---|---|---|
| 4.1 | `platform_data/adapters.py` ç§»é™¤ `from CostView.src.raw_bdib_db import RawBDIBDB`ï¼Œæ”¹ç”¨ `CostViewDatabaseAdapter` æˆ–æ³¨å…¥ `ConnectionManager` | `platform_data/adapters.py` | ä¸­ | MarketReferenceDataAdapter æµ‹è¯• |
| 4.2 | grep æ‰«æç¡®è®¤é›¶ `sqlite3.connect()` å‡ºçŽ°åœ¨ `db/` åŒ…ä¹‹å¤– | CI æ£€æŸ¥ | ä½Ž | è‡ªåŠ¨åŒ–éªŒè¯ |
| 4.3 | æ—§ DB ç±»æ–‡ä»¶æ·»åŠ  `warnings.warn("Use db.repositories instead", DeprecationWarning)` | `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py` | ä½Ž | å¯¼å…¥æµ‹è¯• |
| 4.4 | `PipelineContext` æ—§å­—æ®µï¼ˆ`raw_db`, `proc_db` ç­‰ï¼‰æ·»åŠ  deprecation warning | `pipeline.py` | ä½Ž | ç¼–è¯‘éªŒè¯ |
| 4.5 | æ–°å¢ž CI lint è§„åˆ™ï¼š`sqlite3.connect()` ä¸å¾—å‡ºçŽ°åœ¨ `CostView/src/db/` åŒ…ä¹‹å¤– | CI é…ç½® | ä½Ž | CI è¿è¡Œ |
| 4.6 | æ›´æ–° `docs/spec/project-structure.md`ã€`docs/spec/data-domain.md`ã€`.github/agent.md` ç›¸å…³æè¿° | æ–‡æ¡£ | ä½Ž | äººå·¥å®¡æŸ¥ |

#### è¿­ä»£ 4 éªŒæ”¶æ ‡å‡†

- [ ] `platform_data/` ä¸­é›¶ `from CostView.src.*` å¯¼å…¥ï¼ˆcontracts é™¤å¤–ï¼‰
- [ ] `CostView/src/db/` ä¹‹å¤–é›¶ `sqlite3.connect()`
- [ ] æ—§ DB ç±»å¯¼å…¥æ—¶è§¦å‘ `DeprecationWarning`
- [ ] CI lint è§„åˆ™ç”Ÿæ•ˆ
- [ ] Pipeline å®Œæ•´è¿è¡Œæ— å›žå½’
- [ ] æ–‡æ¡£ä¸Žä»£ç ä¸€è‡´

---

## 5. å—å½±å“æ–‡ä»¶æ¸…å•

### æ–°å¢žæ–‡ä»¶

| æ–‡ä»¶ | è¿­ä»£ | è¯´æ˜Ž |
|---|---|---|
| `CostView/src/db/query_builder.py` | 2 | å¤æ‚åˆ†æžæŸ¥è¯¢é€ƒç”Ÿèˆ±å£ |
| `CostView/src/db/schema/inline_ddl.py` | 3 | 5 ä¸ªæ•°æ®åº“çš„ CREATE TABLE IF NOT EXISTS ç‹¬ç«‹ DDL å‡½æ•° |

### ä¿®æ”¹æ–‡ä»¶

| æ–‡ä»¶ | è¿­ä»£ | è¯´æ˜Ž |
|---|---|---|
| `CostView/src/pipeline.py` | 1, 4 | PipelineContext æ”¹ç”¨ CostViewDatabaseï¼›æ—§å­—æ®µåŠ  deprecation |
| `CostView/src/fill_ingestion.py` | 1 | æ”¹ç”¨ Repository |
| `CostView/src/fill_fetch.py` | 1 | æ”¹ç”¨ Repository |
| `CostView/src/tca_query_service.py` | 2 | æ”¹ç”¨ ConnectionManager + QueryBuilder |
| `CostView/src/execution_history_service.py` | 2 | æ”¹ç”¨ Repository |
| `CostView/src/daily_metrics_calculator.py` | 2 | æ”¹ç”¨ Repository |
| `CostView/src/raw_fills_db.py` | 3, 4 | å†…éƒ¨æ”¹ç”¨ ConnectionManagerï¼›æ·»åŠ  deprecation warning |
| `CostView/src/raw_bdib_db.py` | 3, 4 | åŒä¸Š |
| `CostView/src/fill_bdib_db.py` | 3, 4 | åŒä¸Š |
| `CostView/src/processed_raw_bdib_db.py` | 3, 4 | åŒä¸Š |
| `CostView/src/processed_fills_db/_base.py` | 3 | å†…éƒ¨æ”¹ç”¨ ConnectionManager |
| `CostView/src/validate_raw_fills.py` | 3 | æ”¹ç”¨ Repository |
| `CostView/src/query_cli.py` | 3 | æ”¹ç”¨ Repository |
| `CostView/src/regime/schema.py` | 3 | æ”¹ç”¨ ConnectionManager |
| `CostView/src/regime/migrations/apply.py` | 3 | æ”¹ç”¨ ConnectionManager |
| `CostView/src/regime/fill_regime_tagger.py` | 3 | æ”¹ç”¨ ConnectionManager |
| `CostView/src/db/connection.py` | 3 | å¢žåŠ çº¿ç¨‹æœ¬åœ°è¿žæŽ¥ç¼“å­˜ |
| `CostView/src/db/schema/migrations/manager.py` | 3 | æ¶ˆé™¤æ—§ DB ç±»ä¾èµ– |
| `platform_data/adapters.py` | 4 | ç§»é™¤ RawBDIBDB ç›´æŽ¥å¯¼å…¥ |

### åˆ é™¤æ–‡ä»¶

æ— ã€‚æ—§ DB ç±»ä¿ç•™ä½†æ ‡è®° deprecatedï¼Œå¾…åŽç»­è¿­ä»£ç¡®è®¤æ— è°ƒç”¨åŽåˆ é™¤ã€‚

---

## 6. é£Žé™©ä¸Žç¼“è§£

| é£Žé™© | æ¦‚çŽ‡ | å½±å“ | ç¼“è§£ç­–ç•¥ |
|---|---|---|---|
| `tca_query_service.py`ï¼ˆ60KBï¼‰è¿ç§»å¯¼è‡´ TCA æŠ¥å‘Šå›žå½’ | é«˜ | é«˜ | è¿­ä»£ 2 å…ˆæ¢è¿žæŽ¥æºä¸æ”¹ SQL é€»è¾‘ï¼›å¢žé‡éªŒè¯æ¯ä¸ªæŸ¥è¯¢æ–¹æ³• |
| Pipeline å¹¶è¡Œå†™å…¥ç«žæ€æ¡ä»¶åœ¨è¿ç§»ä¸­æš´éœ² | ä¸­ | é«˜ | `ConnectionManager` çº¿ç¨‹æœ¬åœ°ç¼“å­˜ + WAL æ¨¡å¼ + busy_timeout |
| æ—§ DB ç±» Facade é—æ¼è°ƒç”¨ç‚¹ | ä¸­ | ä¸­ | è¿­ä»£ 1 å…ˆ grep å…¨é‡æ‰«æï¼›è¿­ä»£ 4 CI lint è§„åˆ™ |
| `processed_fills_db` çš„ `_upsert_fixed_schema` åœ¨æ–°æ—§è·¯å¾„é—´ä¸ä¸€è‡´ | ä½Ž | é«˜ | ä¸¤æ¡è·¯å¾„æœ€ç»ˆéƒ½è°ƒç”¨ `ConnectionManager`ï¼Œç¡®ä¿ Pragma ä¸€è‡´ |
| `MigrationManager` åˆå§‹åŒ–åœ¨æ— æ—§ DB ç±»æ—¶å¤±è´¥ | ä¸­ | é«˜ | è¿­ä»£ 3 ç‹¬ç«‹å®žçŽ° schema init DDLï¼Œä¸ä¾èµ–æ—§ç±» |
| `platform_data/adapters.py` ç§»é™¤ RawBDIBDB åŽ MarketReferenceDataAdapter å›žå½’ | ä¸­ | é«˜ | è¿­ä»£ 4 å…ˆåˆ›å»ºä»£ç†å±‚éªŒè¯é€šè¿‡å†åˆ é™¤åŽŸå¯¼å…¥ |

---

## 7. å›žæ»šè§„åˆ™

å¦‚æžœä»»ä½•è¿­ä»£å¯¼è‡´æµ‹è¯•å¤±è´¥æˆ–ç³»ç»Ÿä¸ç¨³å®šï¼š

1. **ç«‹å³å›žæ»š**åˆ°è¯¥è¿­ä»£å¼€å§‹å‰çš„ git commit
2. åœ¨ `iteration-log.md` ä¸­è®°å½•å¤±è´¥ï¼ˆå«è¯Šæ–­æ•°æ®ï¼‰
3. åœ¨ `error-patterns.md` ä¸­è®°å½•å¤±è´¥æ–¹æ¡ˆä»¥é˜²æ­¢é‡è¯•
4. æå‡ºæ›¿ä»£æ–¹æ¡ˆå¹¶è¯´æ˜Žç†ç”±

æ¯ä¸ªè¿­ä»£å¼€å§‹å‰åˆ›å»º git tagï¼ˆå¦‚ `db-subsystem-iter1-start`ï¼‰ï¼Œä¾¿äºŽç²¾ç¡®å›žæ»šã€‚

---

## 8. æž¶æž„å†³ç­–å¾…è®°å½•

å®Œæˆæ­¤ plan åŽï¼Œä»¥ä¸‹å†³ç­–éœ€è¿½åŠ åˆ° `.github/knowledge/architecture-decisions.md`ï¼š

1. **CostView æ•°æ®åº“å­ç³»ç»Ÿç‹¬ç«‹** â€” Protocol è§£è€¦ + ConnectionManager ç»Ÿä¸€ç®¡ç† + Repository è¯»å†™åˆ†ç¦»
2. **QueryBuilder é€ƒç”Ÿèˆ±å£** â€” åˆ†æžåž‹æŸ¥è¯¢é€šè¿‡ QueryBuilder ä¿æŒçµæ´»æ€§ï¼Œä¸å¼ºåˆ¶æ‹†è§£ä¸ºå›ºå®šç­¾å
3. **è·¨æ¨¡å—æ•°æ®å¥‘çº¦å±‚** â€” `platform_data/contracts/` ä½œä¸ºè·¨æ¨¡å— DTO çš„å”¯ä¸€åˆæ³•æ¥æº
4. **ConnectionManager çº¿ç¨‹æœ¬åœ°ç¼“å­˜** â€” é«˜é¢‘æŸ¥è¯¢åœºæ™¯å¤ç”¨åŒçº¿ç¨‹åŒåº“è¿žæŽ¥
5. **æ—§ DB ç±» Deprecation ç­–ç•¥** â€” ä¿ç•™ Facade + deprecation warningï¼Œæ¸è¿›å¼æ·˜æ±°

---

## 9. å·¥ä½œæµçŠ¶æ€æœº

### 9.1 .github/agent.md ä¸ƒé˜¶æ®µçŠ¶æ€æœºå›žé¡¾

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  PLAN    â”‚  â†’â”‚  BUILD   â”‚  â†’â”‚  DIFF    â”‚  â†’â”‚  QA      â”‚  â†’â”‚ APPROVAL â”‚  â†’â”‚  APPLY   â”‚  â†’â”‚  DOCS    â”‚
â”‚ åˆ¶å®šè®¡åˆ’  â”‚   â”‚ æœ€å°å®žçŽ°  â”‚   â”‚ å·®å¼‚å®¡æ ¸ â”‚   â”‚ è´¨é‡æ ¡éªŒ  â”‚   â”‚ äººå·¥æ‰¹å‡†  â”‚   â”‚ åº”ç”¨å˜æ›´ â”‚   â”‚ æ–‡æ¡£æ›´æ–°  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### 9.2 æœ¬è®¡åˆ’çš„è¿­ä»£Ã—çŠ¶æ€æœºæ˜ å°„

æ¯ä¸ªè¿­ä»£**ç‹¬ç«‹ç»åŽ†å®Œæ•´çš„ä¸ƒé˜¶æ®µçŠ¶æ€æœº**ã€‚å‰ä¸€ä¸ªè¿­ä»£çš„ DOCS å®ŒæˆåŽï¼Œæ‰è¿›å…¥ä¸‹ä¸€ä¸ªè¿­ä»£çš„ PLANã€‚

```
è¿­ä»£ 1: PLAN â†’ BUILD â†’ DIFF â†’ QA â†’ APPROVAL â†’ APPLY â†’ DOCS
                                                          â†“
è¿­ä»£ 2: PLAN â†’ BUILD â†’ DIFF â†’ QA â†’ APPROVAL â†’ APPLY â†’ DOCS
                                                          â†“
è¿­ä»£ 3: PLAN â†’ BUILD â†’ DIFF â†’ QA â†’ APPROVAL â†’ APPLY â†’ DOCS
                                                          â†“
è¿­ä»£ 4: PLAN â†’ BUILD â†’ DIFF â†’ QA â†’ APPROVAL â†’ APPLY â†’ DOCS
```

### 9.3 å„çŠ¶æ€çš„è§¦å‘æ¡ä»¶ã€æ‰§è¡Œæ­¥éª¤ä¸Žäº§å‡º

#### PLAN é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | ä¸Šä¸€è¿­ä»£çš„ DOCS å®Œæˆï¼ˆæˆ–é¦–æ¬¡å¯åŠ¨ï¼‰ |
| **Agent è¡Œä¸º** | (1) æŸ¥é˜… `.github/knowledge/architecture-decisions.md` å’Œ `.github/knowledge/iteration-log.md`ï¼›(2) ç¡®è®¤æœ¬è¿­ä»£æ­¥éª¤æ¸…å•ä¸­æ¯ä¸€æ­¥çš„å—å½±å“æ–‡ä»¶å½“å‰çŠ¶æ€ï¼ˆå¿…è¦æ—¶ `read_file` é‡æ–°ç¡®è®¤ï¼‰ï¼›(3) è¾“å‡ºæœ¬è¿­ä»£çš„ç»†åŒ–æ­¥éª¤ã€é£Žé™©æ ‡è®°å’ŒéªŒè¯å‘½ä»¤ï¼›(4) åˆ›å»º git tag `db-subsystem-iter{N}-start` |
| **äººå·¥èŒè´£** | ç¡®è®¤/æ‹’ç»è®¡åˆ’ |
| **äº§å‡º** | æ›´æ–°æœ¬ plan.md ä¸­å½“å‰è¿­ä»£çš„çŠ¶æ€ä¸º `PLAN â†’ ç­‰å¾…æ‰¹å‡†`ï¼›git tag |

#### BUILD é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | PLAN èŽ·å¾—äººå·¥æ‰¹å‡†ï¼ˆ"approved" / "looks good" / "LGTM"ï¼‰ |
| **Agent è¡Œä¸º** | (1) åœ¨ `refactor/architecture` åˆ†æ”¯ä¸ŠæŒ‰æ­¥éª¤æ¸…å•æœ€å°åŒ–å®žçŽ°ï¼›(2) æ¯æ­¥å®ŒæˆåŽè¿è¡Œè¯¥æ­¥éª¤å¯¹åº”çš„å•å…ƒæµ‹è¯•ï¼›(3) ä¼˜å…ˆå¤ç”¨å·²æœ‰ `CostViewDatabase` å’Œ Repository å®žçŽ°ï¼Œä¸é‡å†™å·²æœ‰åŠŸèƒ½ï¼›(4) éµå¾ªé¡¹ç›®ç¼–ç å¥‘çº¦ï¼ˆsnake_caseã€æ–‡ä»¶ â‰¤500 è¡Œã€WARNING æ—¥å¿—ç­‰çº§ï¼‰ |
| **äººå·¥èŒè´£** | æ—  |
| **äº§å‡º** | ä»£ç å˜æ›´ï¼ˆgit working tree changesï¼‰ |

#### DIFF é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | BUILD é˜¶æ®µæ‰€æœ‰æ­¥éª¤å®Œæˆ |
| **Agent è¡Œä¸º** | (1) è¾“å‡º `git diff` ç»Ÿä¸€æ ¼å¼ï¼›(2) é€æ–‡ä»¶è¯´æ˜Žå˜æ›´ç†ç”±ä¸Žé›†æˆç‚¹ï¼›(3) æ£€æŸ¥æ˜¯å¦å¼•å…¥æ–°ä¾èµ–ï¼ˆç¦æ­¢æœªç»å£°æ˜Žçš„æ–°ä¾èµ–ï¼‰ï¼›(4) æ£€æŸ¥æ˜¯å¦è¿ååˆ†å±‚ä¾èµ–æ–¹å‘ |
| **äººå·¥èŒè´£** | åˆæ­¥å®¡æŸ¥å˜æ›´èŒƒå›´ |
| **äº§å‡º** | diff æŠ¥å‘Š |

#### QA é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | DIFF æäº¤å®¡æŸ¥ |
| **Agent è¡Œä¸º** | (1) è¿è¡Œ lintï¼ˆ`ruff check` æˆ–åŒç­‰å·¥å…·ï¼‰ï¼›(2) è¿è¡ŒåŽç«¯æµ‹è¯•ï¼ˆ`python -m unittest CostView.tests -v` æˆ– `pytest`ï¼‰ï¼›(3) è‹¥æ¶‰åŠå‰ç«¯å˜æ›´ï¼Œè¿è¡Œ `npm run build`ï¼›(4) è¿è¡Œ pipeline å›žå½’ï¼ˆ`python -m CostView` å•æ—¥æœŸ smoke testï¼‰ï¼›(5) Bloomberg å­—æ®µå˜æ›´é¢å¤–æ ¡éªŒï¼ˆæœ¬è®¡åˆ’ä¸æ¶‰åŠï¼‰ |
| **äººå·¥èŒè´£** | æŸ¥çœ‹ QA æŠ¥å‘Š |
| **äº§å‡º** | QA æŠ¥å‘Šï¼ˆlint ç»“æžœ + æµ‹è¯•ç»“æžœ + build ç»“æžœ + pipeline å›žå½’ç»“æžœï¼‰ |

#### APPROVAL é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | QA é€šè¿‡ï¼ˆé›¶ lint é”™è¯¯ + é›¶æµ‹è¯•å¤±è´¥ + build é€šè¿‡ + pipeline å›žå½’é€šè¿‡ï¼‰ |
| **Agent è¡Œä¸º** | ç­‰å¾…äººå·¥æ‰¹å‡†ã€‚**ä»…æŽ¥å—** "approved" / "looks good" / "LGTM" |
| **äººå·¥èŒè´£** | **æ˜¾å¼æ‰¹å‡†** |
| **äº§å‡º** | æ‰¹å‡†ç¡®è®¤ |

#### APPLY é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | èŽ·å¾—äººå·¥æ‰¹å‡† |
| **Agent è¡Œä¸º** | (1) å°†å˜æ›´æäº¤åˆ° `refactor/architecture` åˆ†æ”¯ï¼ˆcommit message: `{type}: {description} â€“ iteration #{N}`ï¼‰ï¼›(2) éªŒè¯æäº¤åŽä»£ç ä»å¯è¿è¡Œï¼›(3) è‹¥æ¶‰åŠ Python åŽç«¯å˜æ›´ï¼Œé‡å¯åŽç«¯å¹¶éªŒè¯å¥åº·ç«¯ç‚¹ |
| **äººå·¥èŒè´£** | æ—  |
| **äº§å‡º** | git commit + åŽç«¯é‡å¯éªŒè¯ |

#### DOCS é˜¶æ®µ

| ç»´åº¦ | è¯´æ˜Ž |
|---|---|
| **è§¦å‘æ¡ä»¶** | APPLY å®Œæˆ |
| **Agent è¡Œä¸º** | (1) è¿½åŠ æ¡ç›®åˆ° `.github/knowledge/iteration-log.md`ï¼›(2) å¦‚è§£å†³é”™è¯¯ï¼Œæ£€æŸ¥ `.github/knowledge/error-patterns.md` æ˜¯å¦éœ€è¦å½•å…¥æ–°æ¨¡å¼ï¼ˆå‡ºçŽ° 2+ æ¬¡æ‰å½•å…¥ï¼‰ï¼›(3) å¦‚æ¶‰åŠæž¶æž„å˜æ›´ï¼Œæ›´æ–° `.github/knowledge/architecture-decisions.md`ï¼›(4) å¦‚æ¶‰åŠç”¨æˆ·éœ€æ±‚ï¼Œæ›´æ–° `.github/knowledge/user-needs.md`ï¼›(5) æ›´æ–°æœ¬ plan.md ä¸­å½“å‰è¿­ä»£çš„çŠ¶æ€ä¸º `å®Œæˆ`ï¼Œæ ‡è®°ä¸‹ä¸€è¿­ä»£ä¸º `å¾…å¯åŠ¨`ï¼›(6) æ£€æŸ¥æ˜¯å¦éœ€è¦æ›´æ–° `docs/spec/memory.md`ã€`docs/handoff.md` |
| **äººå·¥èŒè´£** | å®¡æŸ¥æ–‡æ¡£å®Œæ•´æ€§ |
| **äº§å‡º** | çŸ¥è¯†åº“æ›´æ–° + plan.md çŠ¶æ€æ›´æ–° |

### 9.4 çŠ¶æ€æµè½¬å¤±è´¥å¤„ç†

| åœºæ™¯ | å¤„ç† |
|---|---|
| QA å¤±è´¥ | å›žåˆ° BUILD ä¿®å¤ï¼›ä¿®å¤åŽé‡æ–°èµ° DIFF â†’ QA |
| QA è¿žç»­ 3 æ¬¡å¤±è´¥ | åœæ­¢ï¼Œå›žæ»šåˆ° git tagï¼Œè®°å½• `error-patterns.md`ï¼Œæå‡ºæ›¿ä»£æ–¹æ¡ˆ |
| APPROVAL è¢«æ‹’ç» | å›žåˆ° PLAN é‡æ–°åˆ¶å®šæ–¹æ¡ˆ |
| APPLY åŽå‘çŽ°å›žå½’ | ç«‹å³å›žæ»šåˆ° git tagï¼Œè®°å½• `iteration-log.md` å’Œ `error-patterns.md` |

### 9.5 å½“å‰çŠ¶æ€

```
å½“å‰: è¿­ä»£ 3 å·²å®Œæˆ (BUILD + QA)
è¿­ä»£ 1 çŠ¶æ€: âœ… å®Œæˆ â€” Commit 1c20e9b
è¿­ä»£ 2 çŠ¶æ€: âœ… å®Œæˆ
è¿­ä»£ 3 çŠ¶æ€: âœ… å®Œæˆ â€” 81/81 æµ‹è¯•é€šè¿‡ï¼Œdb/ ä¹‹å¤–é›¶è£¸ sqlite3.connect()
è¿­ä»£ 4 çŠ¶æ€: å¾…å¯åŠ¨
ä¸‹ä¸€æ­¥: è¿›å…¥è¿­ä»£ 4 çš„ PLAN é˜¶æ®µ
```

