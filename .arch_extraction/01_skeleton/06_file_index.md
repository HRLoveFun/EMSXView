# å…³é”®æ–‡ä»¶ç´¢å¼•

> åŸºäºŽ cloc è¡Œæ•° + ä¾èµ–å›¾ + æž¶æž„è§’è‰²ç»¼åˆæ ‡æ³¨ã€‚  
> æ ‡ç­¾è¯´æ˜Žï¼š`ðŸ”¥è¶…å¤§` â‰¥500è¡Œ | `âš ï¸è¶…é™` >300è¡Œ(å‰ç«¯)/>500è¡Œ(åŽç«¯) | `ðŸ§±æ— å†…éƒ¨ä¾èµ–` | `ðŸ”—æž¢çº½` è¢«å¤šæ¨¡å—ä¾èµ–

---

## æ ¸å¿ƒæŠ½è±¡ï¼ˆä¸èƒ½åŠ¨ï¼‰â­â­â­

> è·¨æ¨¡å—å…±äº«çš„åŸºç¡€è®¾æ–½ã€API å¥‘çº¦ã€æ•°æ®è®¿é—®å”¯ä¸€å…¥å£ã€‚ä¿®æ”¹éœ€å…¨å‘˜å®¡æ‰¹ã€‚

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `platform_data/adapters.py` | 936 | ðŸ”¥è¶…å¤§ ðŸ”—æž¢çº½ | å…±äº«é€‚é…å±‚â€”â€”è·¨åŸŸæ•°æ®è®¿é—®çš„å”¯ä¸€åˆæ³•å…¥å£ï¼ŒCostView åŽç«¯ä¾èµ– |
| `platform_data/repositories.py` | 866 | ðŸ”¥è¶…å¤§ ðŸ”—æž¢çº½ | å…±äº«ä»“å‚¨å±‚â€”â€”æŒä¹…åŒ–æ•°æ®è®¿é—®ï¼Œæ— å†…éƒ¨ä¾èµ– |
| `platform_data/__init__.py` | 98 | ðŸ§± | æ¨¡å—å…¥å£ï¼Œå¯¼å‡º adapters |
| `ExecutionView/backend/api/services/bloomberg_adapter.py` | 2119 | ðŸ”¥è¶…å¤§ ðŸ”—æž¢çº½ | Bloomberg EMSX æ ¸å¿ƒé€‚é…å™¨ï¼šè®¢å•/è·¯ç”±/è¡Œæƒ…è®¢é˜…ã€å­—æ®µè§£æžã€äº‹ä»¶åˆ†å‘ |
| `ExecutionView/backend/api/schemas.py` | 614 | âš ï¸è¶…é™ ðŸ§±ðŸ”—æž¢çº½ | Pydantic API å¥‘çº¦ï¼Œå‰åŽç«¯æŽ¥å£é•œåƒçš„æºå¤´ï¼Œæ— å†…éƒ¨ä¾èµ– |
| `ExecutionView/backend/api/db.py` | 56 | ðŸ§± | SQLite åˆå§‹åŒ– + migration æ‰§è¡Œ |
| `ExecutionView/backend/api/deps.py` | 43 | ðŸ”—æž¢çº½ | FastAPI ä¾èµ–æ³¨å…¥ï¼šç»„è£…æ‰€æœ‰ service å•ä¾‹ï¼Œå®¡è®¡æ—¥å¿—å¼‚æ­¥æŒä¹…åŒ– |

## æ•°æ®å±‚ â­â­

> æ•°æ®åº“å®šä¹‰ã€ä»“å‚¨å®žçŽ°ã€Schema è¿ç§»ã€‚

### CostView æ•°æ®åº“

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `CostView/src/schema.py` | 215 | ðŸ§± | è¡¨ç»“æž„å®šä¹‰ï¼ˆraw_fills / processed_fills / aggregated_fills ç­‰ï¼‰ |
| `CostView/src/database.py` | 98 | ðŸ§± | æ•°æ®åº“è¿žæŽ¥å·¥åŽ‚ |
| `CostView/src/database_access.py` | 104 | ðŸ§± | é€šç”¨æ•°æ®è®¿é—®å±‚åŸºç±» |
| `CostView/src/raw_fills_db.py` | 516 | âš ï¸è¶…é™ | åŽŸå§‹å¡«å…… CRUD |
| `CostView/src/processed_fills_db.py` | 685 | âš ï¸è¶…é™ | å·²å¤„ç†å¡«å…… CRUD + èšåˆæŸ¥è¯¢ |
| `CostView/src/fill_bdib_db.py` | 100 | | å¡«å……-BDIB å…³è”æ•°æ®åº“ |
| `CostView/src/raw_bdib_db.py` | 272 | | åŽŸå§‹ BDIB è¡Œæƒ…å­˜å‚¨ |
| `CostView/src/processed_raw_bdib_db.py` | 134 | | å·²å¤„ç† BDIB æ•°æ® |
| `CostView/src/processed_bdib_db.py` | 13 | | å·²å¤„ç† BDIBï¼ˆæ—§ï¼‰ |
| `CostView/src/regime/schema.py` | 31 | | å¸‚åœºçŠ¶æ€æ•°æ®åº“ Schema |
| `CostView/src/storage/regime_reader.py` | 58 | | å¸‚åœºçŠ¶æ€æ•°æ®è¯»å– |

### ExecutionView æ•°æ®åº“

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/models/execution_state.py` | 46 | ðŸ§± | æ‰§è¡ŒçŠ¶æ€ dataclass æ¨¡åž‹ |
| `ExecutionView/backend/api/models/route_plan.py` | 113 | | è·¯ç”±è®¡åˆ’ dataclass æ¨¡åž‹ |
| `ExecutionView/backend/api/models/parent_child_orders.py` | 73 | | çˆ¶å­è®¢å• dataclass æ¨¡åž‹ |
| `ExecutionView/backend/api/repositories/orders.py` | 47 | | è®¢å•ä»“å‚¨ |
| `ExecutionView/backend/api/repositories/routes.py` | 48 | | è·¯ç”±ä»“å‚¨ |
| `ExecutionView/backend/api/repositories/parent_child_repository.py` | 82 | | çˆ¶å­æ‰§è¡Œä»“å‚¨ |
| `ExecutionView/backend/api/repositories/audit.py` | 35 | | å®¡è®¡æ—¥å¿—ä»“å‚¨ |
| `ExecutionView/backend/api/migrations/001_init_execution_schema.sql` | 45 | | åˆå§‹åŒ–è¿ç§» |
| `ExecutionView/backend/api/migrations/002_parent_child_execution.sql` | 43 | | çˆ¶å­æ‰§è¡Œè¿ç§» |
| `ExecutionView/backend/api/migrations/003_route_plan.sql` | 72 | | è·¯ç”±è®¡åˆ’è¿ç§» |

## ä¸šåŠ¡é€»è¾‘ â­â­

> æœåŠ¡å±‚ã€è·¯ç”±å±‚ã€ç®¡é“ç¼–æŽ’â€”â€”ç³»ç»Ÿçš„æ ¸å¿ƒå†³ç­–é€»è¾‘ã€‚

### ExecutionView åŽç«¯æœåŠ¡å±‚

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/services/route_engine.py` | 333 | ðŸ”—æž¢çº½ | è·¯ç”±å¼•æ“Žâ€”â€”è®¢å•â†’å­å•æ‹†åˆ†å†³ç­–ã€è‡ªåŠ¨è·¯ç”±è§„åˆ™åº”ç”¨ |
| `ExecutionView/backend/api/services/route_service.py` | 209 | ðŸ”—æž¢çº½ | è·¯ç”± CRUD + æäº¤/ä¿®æ”¹/å–æ¶ˆï¼Œä¸Ž Bloomberg äº¤äº’ |
| `ExecutionView/backend/api/services/batch_route_service.py` | 474 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | æ‰¹é‡è·¯ç”±æœåŠ¡â€”â€”å¹¶å‘æäº¤ã€è¿›åº¦è¿½è¸ªã€ç­–ç•¥è´¹çŽ‡è¯Šæ–­ |
| `ExecutionView/backend/api/services/compliance_service.py` | 278 | | åˆè§„æ£€æŸ¥â€”â€”ç¢Žè‚¡é™åˆ¶ã€æ‰‹åŠ¨ç»çºªå•†å®¡æ‰¹ |
| `ExecutionView/backend/api/services/algo_scheduler.py` | 190 | ðŸ”—æž¢çº½ | ç®—æ³•è°ƒåº¦å™¨â€”â€”å®šæ—¶/æ¡ä»¶è§¦å‘å­å•æäº¤ |
| `ExecutionView/backend/api/services/benchmark_engine.py` | 117 | | åŸºå‡†å¼•æ“Žâ€”â€”VWAP/Arrival ç­‰åŸºå‡†ä»·è®¡ç®— |
| `ExecutionView/backend/api/services/order_projections.py` | 125 | ðŸ§± | è®¢å•æŠ•å½±â€”â€”UI æ‰€éœ€çš„èšåˆ/è®¡ç®—å­—æ®µ |
| `ExecutionView/backend/api/services/route_projections.py` | 51 | ðŸ§± | è·¯ç”±æŠ•å½±â€”â€”UI æ‰€éœ€çš„èšåˆ/è®¡ç®—å­—æ®µ |
| `ExecutionView/backend/api/services/config_service.py` | 39 | ðŸ§± | è¿è¡Œæ—¶é…ç½®è¯»å†™ï¼ˆç­–ç•¥è´¹çŽ‡ã€é£ŽæŽ§å‚æ•°ï¼‰ |

### ExecutionView åŽç«¯è·¯ç”±å±‚

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/routers/orders.py` | 482 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | è®¢å•+æ‰§è¡Œ APIï¼ˆ15+ ç«¯ç‚¹ï¼‰ï¼Œä¾èµ–å‡ ä¹Žæ‰€æœ‰ service |
| `ExecutionView/backend/api/routers/route_plans.py` | 491 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | è·¯ç”±è®¡åˆ’ + RouteEngine + å­å•ææ¡ˆ API |
| `ExecutionView/backend/api/routers/routes.py` | 160 | | è·¯ç”±æ“ä½œ API |
| `ExecutionView/backend/api/routers/broker.py` | 192 | | ç»çºªå•†/ç­–ç•¥/ç®—æ³•æŸ¥è¯¢ API |
| `ExecutionView/backend/api/routers/marketview.py` | 409 | âš ï¸è¶…é™ ðŸ§± | å¸‚åœºå¿«ç…§+ç›˜å†…ç‰¹å¾+æ‰§è¡Œäº¤æŽ¥ API |
| `ExecutionView/backend/api/routers/costview.py` | 434 | âš ï¸è¶…é™ ðŸ§± | TCA åˆ†æž/è®°åˆ†å¡/ç®¡é“è§¦å‘ API |
| `ExecutionView/backend/api/routers/market_broker_mapping.py` | 127 | | ç»çºªå•†-å¸‚åœºæ˜ å°„ CRUD API |
| `ExecutionView/backend/api/routers/execution_history.py` | 103 | | æ‰§è¡ŒåŽ†å²æŸ¥è¯¢ API |
| `ExecutionView/backend/api/routers/_pipeline_jobs.py` | 190 | | CostView ç®¡é“å­è¿›ç¨‹ç®¡ç† |
| `ExecutionView/backend/api/routers/auth.py` | 19 | | è®¤è¯ API |
| `ExecutionView/backend/api/routers/connection.py` | 51 | | è¿žæŽ¥/å¥åº·æ£€æŸ¥ API |
| `ExecutionView/backend/api/routers/realtime.py` | 57 | | WebSocket å®žæ—¶æŽ¨é€ |

### CostView æ ¸å¿ƒç®¡é“

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `CostView/src/pipeline.py` | 808 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | **ç®¡é“ç¼–æŽ’å™¨**â€”â€”ä¾èµ–å‡ ä¹Žæ‰€æœ‰ CostView æ¨¡å—ï¼Œåè°ƒ fetchâ†’processâ†’aggregateâ†’BDIBâ†’attribution |
| `CostView/src/tca_query_service.py` | 1082 | ðŸ”¥è¶…å¤§ | TCA æŸ¥è¯¢æœåŠ¡â€”â€”å¤šç»´åº¦å½’å› åˆ†æžã€èšåˆæŸ¥è¯¢ |
| `CostView/src/fill_fetch.py` | 773 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | Bloomberg EMSX å¡«å……æ•°æ®èŽ·å–ï¼Œå«å¢žé‡/åŽ†å²æ¨¡å¼ |
| `CostView/src/fill_ingestion.py` | 321 | | å¡«å……æ‘„å…¥â€”â€”æ¸…æ´—â†’å¤„ç†â†’å…¥åº“ç¼–æŽ’ |
| `CostView/src/fill_processor.py` | 168 | | å¡«å……å¤„ç†â€”â€”å­—æ®µæ˜ å°„ã€è®¡ç®— |
| `CostView/src/fill_cleaner.py` | 168 | | å¡«å……æ¸…æ´—â€”â€”åŽ»é‡ã€æ—¶åŒºã€å¼‚å¸¸å€¼ |
| `CostView/src/fill_aggregator.py` | 123 | | å¡«å……èšåˆâ€”â€”æ—¥åº¦/ç­–ç•¥çº§æ±‡æ€» |
| `CostView/src/daily_metrics_calculator.py` | 257 | | BDIB æ¯æ—¥æŒ‡æ ‡è®¡ç®—ï¼ˆADV/VWAP ç­‰ï¼‰ |
| `CostView/src/validate_raw_fills.py` | 405 | âš ï¸è¶…é™ | åŽŸå§‹å¡«å……å®Œæ•´æ€§éªŒè¯ |
| `CostView/src/__main__.py` | 246 | | CostView CLI å…¥å£ï¼ˆfetch/process/aggregate/pipeline/query/scheduleï¼‰ |

### CostView å½’å› åˆ†æž

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `CostView/src/attribution/writer.py` | 288 | | å½’å› ç»“æžœå†™å…¥ |
| `CostView/src/attribution/aggregator.py` | 212 | | å½’å› èšåˆè®¡ç®— |
| `CostView/src/attribution/benchmarks.py` | 129 | | åŸºå‡†ä»·è®¡ç®—ï¼ˆVWAP/Arrival/TWAPï¼‰ |
| `CostView/src/attribution/recommender.py` | 71 | | æ‰§è¡Œå»ºè®®ç”Ÿæˆ |
| `CostView/src/attribution/metrics.py` | 39 | | å½’å› æŒ‡æ ‡å®šä¹‰ |
| `CostView/src/attribution/config.py` | 70 | | å½’å› é…ç½®ï¼ˆç®—æ³•/Benchmark/æœŸé™ï¼‰ |

### CostView å¸‚åœºçŠ¶æ€ï¼ˆRegimeï¼‰

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `CostView/src/regime/fill_regime_tagger.py` | 175 | | å¡«å……â†’å¸‚åœºçŠ¶æ€æ ‡ç­¾æ˜ å°„ |
| `CostView/src/regime/vol_regime.py` | 122 | | æ³¢åŠ¨çŽ‡çŠ¶æ€åˆ¤å®š |
| `CostView/src/regime/trend_regime.py` | 87 | | è¶‹åŠ¿çŠ¶æ€åˆ¤å®š |
| `CostView/src/regime/liquidity_regime.py` | 75 | | æµåŠ¨æ€§çŠ¶æ€åˆ¤å®š |
| `CostView/src/regime/market_index_loader.py` | 141 | | å¸‚åœºæŒ‡æ•°æ•°æ®åŠ è½½ |
| `CostView/src/regime/time_bucket.py` | 66 | | æ—¶é—´æ¡¶åˆ’åˆ† |
| `CostView/src/regime/market_code.py` | 33 | | å¸‚åœºä»£ç æ˜ å°„ |
| `CostView/src/regime/config.py` | 83 | | å¸‚åœºçŠ¶æ€é…ç½® |
| `CostView/src/regime/migrations/apply.py` | 71 | | æ•°æ®åº“è¿ç§»æ‰§è¡Œå™¨ |
| `CostView/src/regime/migrations/v0_to_v1.sql` | 179 | | è¿ç§» v0â†’v1 |
| `CostView/src/regime/migrations/v1_to_v2.sql` | 55 | | è¿ç§» v1â†’v2 |
| `CostView/src/regime/migrations/v2_to_v3.sql` | 89 | | è¿ç§» v2â†’v3 |

## é›†æˆå±‚ â­

> å¤–éƒ¨ç³»ç»ŸæŽ¥å£ã€å®žæ—¶é€šä¿¡ç½‘å…³ã€äº‹ä»¶åºåˆ—åŒ–ã€‚

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/services/bloomberg_interface.py` | 41 | ðŸ§± | Bloomberg API åº•å±‚å°è£…ï¼ˆblpapi Session ç®¡ç†ï¼‰ |
| `ExecutionView/backend/api/services/realtime_gateway.py` | 80 | ðŸ”—æž¢çº½ | WebSocket æŽ¨é€ç½‘å…³â€”â€”è®¢å•/è·¯ç”±å˜æ›´å¹¿æ’­ |
| `ExecutionView/backend/api/services/event_serializers.py` | 41 | ðŸ§± | Bloomberg äº‹ä»¶â†’Pydantic åºåˆ—åŒ– |
| `ExecutionView/backend/api/auth.py` | 122 | | JWT è®¤è¯ä¸­é—´ä»¶ |
| `ExecutionView/backend/api/services/auth_service.py` | 29 | | è®¤è¯æœåŠ¡ï¼ˆBloomberg UUID æ ¡éªŒï¼‰ |
| `CostView/src/emsx_client.py` | 239 | | Bloomberg EMSX SOAP/REST å®¢æˆ·ç«¯ |
| `CostView/src/bdib_fetcher.py` | 301 | | Bloomberg BDIB è¡Œæƒ…æ•°æ®èŽ·å– |
| `CostView/src/fill_bdib_integrated.py` | 207 | | å¡«å……-BDIB è”åˆèŽ·å– |
| `CostView/src/downstream_interface.py` | 97 | | ä¸‹æ¸¸ç³»ç»ŸæŽ¥å£ï¼ˆæŸ¥è¯¢/å¯¼å‡ºï¼‰ |
| `CostView/src/execution_history_service.py` | 122 | | æ‰§è¡ŒåŽ†å²æŸ¥è¯¢æœåŠ¡ |

## é…ç½®/å·¥å…· â­

> é…ç½®å•ä¾‹ã€é™æ€æ•°æ®ã€å‰ç«¯æœåŠ¡/ç±»åž‹/hookã€è¿ç»´è„šæœ¬ã€‚

### åŽç«¯é…ç½®ä¸Žè£…é…

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/config.py` | 48 | ðŸ§± | åŽç«¯å…¨å±€é…ç½®å•ä¾‹ï¼ˆBloomberg/DB/JWT/CORS/é£ŽæŽ§ï¼‰ |
| `ExecutionView/backend/api/service_provider.py` | 187 | ðŸ”—æž¢çº½ | æœåŠ¡å·¥åŽ‚â€”â€”ç»„è£…æ‰€æœ‰ä»“å‚¨+æœåŠ¡å®žä¾‹ï¼ŒDI å®¹å™¨ |
| `ExecutionView/backend/api/main.py` | 254 | ðŸ”—æž¢çº½ | FastAPI åº”ç”¨å…¥å£ï¼šè·¯ç”±æ³¨å†Œã€ç”Ÿå‘½å‘¨æœŸã€Bloomberg å¼‚æ­¥è¿žæŽ¥ |
| `ExecutionView/backend/api/start_server.py` | 18 | | å¤‡ç”¨å¯åŠ¨å™¨ |
| `CostView/src/processing_config.py` | 102 | ðŸ§±ðŸ”—æž¢çº½ | CostView ç®¡é“ä¸­å¿ƒåŒ–é…ç½®â€”â€”ç›®å½•/DBè·¯å¾„/å‚æ•° |
| `CostView/src/secure_config.py` | 218 | | Bloomberg å‡­æ®ç®¡ç†ï¼ˆUUID + çŽ¯å¢ƒå˜é‡/JSONï¼‰ |
| `CostView/src/exchange_tz.py` | 99 | | äº¤æ˜“æ‰€æ—¶åŒºæ˜ å°„ |
| `CostView/src/mapping.py` | 177 | | é€šç”¨å­—æ®µæ˜ å°„å·¥å…· |
| `CostView/src/order_label.py` | 69 | | è®¢å•æ ‡ç­¾ç”Ÿæˆ |
| `CostView/src/query_cli.py` | 175 | | äº¤äº’å¼ TCA æŸ¥è¯¢ CLI |

### é™æ€æ•°æ®æ–‡ä»¶

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/data/broker_algorithms.json` | 16819 | ðŸ”¥è¶…å¤§ | ç»çºªå•†ç®—æ³•é…ç½®ï¼ˆ~300 ç®—æ³•ï¼‰ï¼Œå¯åŠ¨æ—¶åŠ è½½ |
| `ExecutionView/backend/api/data/market_broker_mapping.json` | 360 | | å¸‚åœº-ç»çºªå•†é»˜è®¤æ˜ å°„ |
| `ExecutionView/backend/api/data/broker_hand_instruction.json` | 8 | | æ‰‹åŠ¨æ‰§è¡ŒæŒ‡ä»¤é…ç½® |

### å‰ç«¯â€”â€”æœåŠ¡å±‚

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/services/api.ts` | 587 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | æ ¸å¿ƒ HTTP å®¢æˆ·ç«¯â€”â€”æ‰€æœ‰åŽç«¯ API è°ƒç”¨ |
| `ExecutionView/frontend/src/services/realtime.ts` | 201 | | WebSocket å®¢æˆ·ç«¯ |
| `ExecutionView/frontend/src/services/strategy-data-service.ts` | 243 | âš ï¸è¶…é™ | ç­–ç•¥æ•°æ®ç®¡ç†æœåŠ¡ |
| `ExecutionView/frontend/src/services/handoff-api.ts` | 149 | | äº¤æŽ¥ API æœåŠ¡ |
| `ExecutionView/frontend/src/modules/costview/services/api.ts` | 143 | | CostView ä¸“ç”¨ API |
| `ExecutionView/frontend/src/modules/marketview/services/api.ts` | 87 | | MarketView ä¸“ç”¨ API |
| `ExecutionView/frontend/src/modules/databaseview/services/api.ts` | 88 | | DatabaseView ä¸“ç”¨ API |

### å‰ç«¯â€”â€”ç±»åž‹å®šä¹‰

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/types/index.ts` | 533 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | å…¨å±€ TypeScript ç±»åž‹â€”â€”é¡»ä¸ŽåŽç«¯ schemas.py é•œåƒä¸€è‡´ |
| `ExecutionView/frontend/src/modules/costview/types.ts` | 198 | | CostView ç±»åž‹ |
| `ExecutionView/frontend/src/modules/marketview/types.ts` | 148 | | MarketView ç±»åž‹ |
| `ExecutionView/frontend/src/modules/databaseview/types.ts` | 124 | | DatabaseView ç±»åž‹ |

### å‰ç«¯â€”â€”Hooksï¼ˆçŠ¶æ€å±‚ï¼‰

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/hooks/use-execution-view-data.ts` | 375 | âš ï¸è¶…é™ ðŸ”—æž¢çº½ | ä¸»æ•°æ® hookâ€”â€”è®¢å•/è·¯ç”±/æ‰§è¡ŒçŠ¶æ€èšåˆ |
| `ExecutionView/frontend/src/hooks/use-broker-algorithms.ts` | 294 | | ç»çºªå•†ç®—æ³• hook |
| `ExecutionView/frontend/src/hooks/use-market-broker-mapping.ts` | 94 | | ç»çºªå•†æ˜ å°„ hook |
| `ExecutionView/frontend/src/hooks/use-app-shell-state.ts` | 153 | | åº”ç”¨å£³çŠ¶æ€ hook |
| `ExecutionView/frontend/src/hooks/use-startup-status.ts` | 148 | | å¯åŠ¨çŠ¶æ€ hook |
| `ExecutionView/frontend/src/hooks/use-handoff-contracts.tsx` | 117 | | äº¤æŽ¥åˆçº¦ hook |
| `ExecutionView/frontend/src/hooks/use-trade-hotkeys.tsx` | 133 | | äº¤æ˜“å¿«æ·é”® hook |
| `ExecutionView/frontend/src/hooks/use-orders-stream.ts` | 41 | | è®¢å•æµ hook |
| `ExecutionView/frontend/src/hooks/use-routes-stream.ts` | 41 | | è·¯ç”±æµ hook |
| `ExecutionView/frontend/src/hooks/use-mobile.ts` | 15 | | ç§»åŠ¨ç«¯æ£€æµ‹ hook |

### å‰ç«¯â€”â€”æ•°æ®/æ˜ å°„

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/data/broker-exchange-mapping.ts` | 338 | | ç»çºªå•†-äº¤æ˜“æ‰€æ˜ å°„ |
| `ExecutionView/frontend/src/data/exchange-region-mapping.ts` | 44 | | äº¤æ˜“æ‰€-åŒºåŸŸæ˜ å°„ |

### å‰ç«¯â€”â€”å·¥å…·åº“

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/lib/cache-manager.ts` | 205 | | LocalStorage ç¼“å­˜ç®¡ç† |
| `ExecutionView/frontend/src/lib/monitor-conditions.ts` | 174 | | ç›‘æŽ§æ¡ä»¶å®šä¹‰ |
| `ExecutionView/frontend/src/lib/health-palette.ts` | 88 | | å¥åº·çŠ¶æ€é…è‰² |
| `ExecutionView/frontend/src/lib/format-utils.ts` | 29 | | æ ¼å¼åŒ–å·¥å…· |
| `ExecutionView/frontend/src/lib/reconcile-settings.ts` | 29 | | è®¾ç½®å¯¹è´¦å·¥å…· |
| `ExecutionView/frontend/src/lib/table-constants.ts` | 57 | | è¡¨æ ¼å¸¸é‡ |
| `ExecutionView/frontend/src/lib/utils.ts` | 5 | | é€šç”¨å·¥å…· |

### å‰ç«¯â€”â€”æ ¸å¿ƒ UI ç»„ä»¶ï¼ˆä¸šåŠ¡å¤æ‚åº¦é«˜ï¼‰

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/components/batch-route-order-dialog.tsx` | 1247 | ðŸ”¥è¶…å¤§ âš ï¸è¶…é™ | æ‰¹é‡è·¯ç”±å¯¹è¯æ¡†â€”â€”æœ€å¤æ‚çš„å‰ç«¯ç»„ä»¶ |
| `ExecutionView/frontend/src/sections/SettingsBoard.tsx` | 1102 | ðŸ”¥è¶…å¤§ âš ï¸è¶…é™ | è®¾ç½®é¢æ¿ |
| `ExecutionView/frontend/src/components/route-modify-dialogs.tsx` | 893 | âš ï¸è¶…é™ | è·¯ç”±ä¿®æ”¹å¯¹è¯æ¡†ç»„ |
| `ExecutionView/frontend/src/sections/RouteTable.tsx` | 866 | âš ï¸è¶…é™ | è·¯ç”±è¡¨æ ¼ |
| `ExecutionView/frontend/src/sections/OrderTable.tsx` | 681 | âš ï¸è¶…é™ | è®¢å•è¡¨æ ¼ |
| `ExecutionView/frontend/src/components/ui/sidebar.tsx` | 661 | âš ï¸è¶…é™ | ä¾§è¾¹æ å¯¼èˆª |
| `ExecutionView/frontend/src/components/route-plan-manager.tsx` | 617 | âš ï¸è¶…é™ | è·¯ç”±è®¡åˆ’ç®¡ç†å™¨ |
| `ExecutionView/frontend/src/sections/MonitorBoard.tsx` | 574 | âš ï¸è¶…é™ | ç›‘æŽ§é¢æ¿ |
| `ExecutionView/frontend/src/components/batch-operation-dialogs.tsx` | 497 | âš ï¸è¶…é™ | æ‰¹é‡æ“ä½œå¯¹è¯æ¡† |
| `ExecutionView/frontend/src/components/unified-modify-route-dialog.tsx` | 486 | âš ï¸è¶…é™ | ç»Ÿä¸€è·¯ç”±ä¿®æ”¹å¯¹è¯æ¡† |
| `ExecutionView/frontend/src/sections/BatchOperationPanel.tsx` | 308 | | æ‰¹é‡æ“ä½œé¢æ¿ |
| `ExecutionView/frontend/src/components/market-broker-mapping-section.tsx` | 285 | | ç»çºªå•†æ˜ å°„é…ç½®åŒº |
| `ExecutionView/frontend/src/components/algo-launch-dialog.tsx` | 283 | | ç®—æ³•å¯åŠ¨å¯¹è¯æ¡† |
| `ExecutionView/frontend/src/components/order-modify-dialog.tsx` | 270 | | è®¢å•ä¿®æ”¹å¯¹è¯æ¡† |
| `ExecutionView/frontend/src/sections/ExecutionBoard.tsx` | 268 | | æ‰§è¡Œé¢æ¿ |
| `ExecutionView/frontend/src/components/rate-diagnostic-dialog.tsx` | 266 | | ç­–ç•¥è´¹çŽ‡è¯Šæ–­å¯¹è¯æ¡† |
| `ExecutionView/frontend/src/components/strategy-data-manager.tsx` | 255 | | ç­–ç•¥æ•°æ®ç®¡ç†å™¨ |
| `ExecutionView/frontend/src/components/sub-order-review-panel.tsx` | 240 | | å­å•å®¡æ ¸é¢æ¿ |

### å‰ç«¯â€”â€”ä¸šåŠ¡æ¨¡å—

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx` | 795 | âš ï¸è¶…é™ | MarketView æ¨¡å—å£³ |
| `ExecutionView/frontend/src/modules/costview/CostViewModule.tsx` | 265 | | CostView æ¨¡å—å£³ |
| `ExecutionView/frontend/src/modules/costview/components/ScorecardView.tsx` | 447 | âš ï¸è¶…é™ | TCA è®°åˆ†å¡è§†å›¾ |
| `ExecutionView/frontend/src/modules/costview/components/AnalysisView.tsx` | 223 | | å½’å› åˆ†æžè§†å›¾ |
| `ExecutionView/frontend/src/modules/costview/components/ConfigureView.tsx` | 193 | | é…ç½®è§†å›¾ |
| `ExecutionView/frontend/src/modules/costview/components/OverviewView.tsx` | 178 | | æ€»è§ˆè§†å›¾ |
| `ExecutionView/frontend/src/modules/costview/components/PriceDynamicsChart.tsx` | 133 | | ä»·æ ¼åŠ¨æ€å›¾ |
| `ExecutionView/frontend/src/modules/costview/components/RegimeDistributionPanel.tsx` | 110 | | å¸‚åœºçŠ¶æ€åˆ†å¸ƒé¢æ¿ |
| `ExecutionView/frontend/src/modules/costview/components/VolumeDynamicsChart.tsx` | 109 | | æˆäº¤é‡åŠ¨æ€å›¾ |
| `ExecutionView/frontend/src/modules/costview/lib/export.ts` | 276 | | CostView å¯¼å‡ºåŠŸèƒ½ |
| `ExecutionView/frontend/src/modules/costview/lib/thresholds.ts` | 222 | | TCA é˜ˆå€¼é€»è¾‘ |
| `ExecutionView/frontend/src/modules/costview/lib/storage.ts` | 124 | | CostView LocalStorage |
| `ExecutionView/frontend/src/modules/databaseview/DatabaseViewModule.tsx` | 134 | | DatabaseView æ¨¡å—å£³ |
| `ExecutionView/frontend/src/modules/databaseview/components/SchemaSamplePanel.tsx` | 289 | | Schema é‡‡æ ·é¢æ¿ |
| `ExecutionView/frontend/src/modules/databaseview/components/DatabaseDetailDrawer.tsx` | 151 | | æ•°æ®åº“è¯¦æƒ…æŠ½å±‰ |
| `ExecutionView/frontend/src/modules/marketview/lib/workspace.ts` | 29 | | MarketView å·¥ä½œåŒº |

### å‰ç«¯â€”â€”åº”ç”¨å£³

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/App.tsx` | 345 | | åº”ç”¨æ ¹ç»„ä»¶ |
| `ExecutionView/frontend/src/main.tsx` | 9 | | React å…¥å£ |
| `ExecutionView/frontend/src/index.css` | 137 | | å…¨å±€æ ·å¼ |
| `ExecutionView/frontend/src/sections/WorkspaceModuleTabs.tsx` | 123 | | å·¥ä½œåŒºæ¨¡å—æ ‡ç­¾ |
| `ExecutionView/frontend/src/sections/ExecutionViewTabs.tsx` | 100 | | æ‰§è¡Œè§†å›¾æ ‡ç­¾ |
| `ExecutionView/frontend/src/sections/Toolbar.tsx` | 203 | | å·¥å…·æ  |
| `ExecutionView/frontend/src/sections/ToastContainer.tsx` | 86 | | æ¶ˆæ¯æç¤ºå®¹å™¨ |
| `ExecutionView/frontend/src/sections/LazyOrderBoard.tsx` | 133 | | æ‡’åŠ è½½è®¢å•é¢æ¿ |
| `ExecutionView/frontend/src/components/startup-gate.tsx` | 112 | | å¯åŠ¨é—¨æŽ§ç»„ä»¶ |

### å‰ç«¯â€”â€”Stream Store

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/frontend/src/stores/order-stream-store.ts` | 39 | | è®¢å•æµçŠ¶æ€å­˜å‚¨ |
| `ExecutionView/frontend/src/stores/route-stream-store.ts` | 39 | | è·¯ç”±æµçŠ¶æ€å­˜å‚¨ |

### è¿ç»´è„šæœ¬ï¼ˆå…³é”®ï¼‰

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `scripts/workflow/auto_runner.py` | 582 | âš ï¸è¶…é™ | CI è‡ªåŠ¨åŒ– CLIâ€”â€”run-step/check-step/run-all |
| `scripts/import_excel_fills.py` | 590 | âš ï¸è¶…é™ | Excel å¡«å……å¯¼å…¥ï¼ˆå« HKâ†’NY æ—¶åŒºè½¬æ¢ï¼‰ |
| `scripts/service-manager.ps1` | 519 | âš ï¸è¶…é™ | æ ¸å¿ƒæœåŠ¡ç®¡ç†å™¨ï¼ˆstart/stop/restart/status/logsï¼‰ |
| `scripts/fetch_and_inspect.py` | 211 | | èŽ·å–+é€æ­¥æ£€æŸ¥å¡«å……æ•°æ® |
| `scripts/mcp/knowledge-server.py` | 149 | | MCP çŸ¥è¯†æœåŠ¡å™¨ |
| `scripts/deploy/deploy.sh` | 193 | | Docker Compose ç”Ÿäº§éƒ¨ç½² |
| `scripts/workflow/sync_execution_status.py` | 202 | | äº¤ä»˜çŠ¶æ€åŒæ­¥ |
| `scripts/workflow/validate_phase_gate.py` | 154 | | å†²åˆºé—¨éªŒè¯ |

## Legacy / å¾…æ¸…ç† âš ï¸

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `CostView/frontend/src/README.md` | 8 | | é—ç•™ CostView å‰ç«¯å ä½ï¼Œå·²åºŸå¼ƒ |
| `CostView/src/outdated_tickers.py` | 68 | | è¿‡æ—¶è‚¡ç¥¨ä»£ç æ£€æµ‹â€”â€”åç§°æš—ç¤ºå¾…æ¸…ç† |
| `CostView/src/regime/sync_macro_calendar.py` | 79 | | å‚ç…§æ•°æ®åŒæ­¥è„šæœ¬â€”â€”åº”åˆå¹¶åˆ°ç»Ÿä¸€åŠ è½½æµç¨‹ |
| `CostView/src/regime/sync_market_mapping.py` | 72 | | å‚ç…§æ•°æ®åŒæ­¥è„šæœ¬â€”â€”åº”åˆå¹¶ |
| `CostView/src/regime/sync_macro_event_dict.py` | 46 | | å‚ç…§æ•°æ®åŒæ­¥è„šæœ¬â€”â€”åº”åˆå¹¶ |
| `ExecutionView/backend/api/routers/database.py` | 49 | | æ•°æ®åº“ç®¡ç†è·¯ç”±â€”â€”180 è¡Œæ³¨é‡Šï¼Œè°ƒè¯•/è¿ç»´ç”¨é€” |
| `ExecutionView/backend/api/routers/debug.py` | 92 | | è°ƒè¯•è·¯ç”±â€”â€”ä»…å¼€å‘çŽ¯å¢ƒä½¿ç”¨ |
| `ExecutionView/backend/api/.pytest_cache/README.md` | 5 | | åº”åŠ å…¥ .gitignore |
| `scripts/_archive/2026-04-28/*` | â€” | | å·²å½’æ¡£è¯Šæ–­è„šæœ¬ï¼Œå¯åˆ é™¤ |
| `scripts/diagnose/diagnose_orders_display.py` | 177 | | ä¸€æ¬¡æ€§è¯Šæ–­è„šæœ¬ |
| `scripts/diagnose/diagnose_exchange_ticker_issue.py` | 171 | | ä¸€æ¬¡æ€§è¯Šæ–­è„šæœ¬ |
| `scripts/diagnose/diagnose_odd_lot.py` | 80 | | ä¸€æ¬¡æ€§è¯Šæ–­è„šæœ¬ |
| `scripts/diagnose/diagnose_market_data.py` | 63 | | ä¸€æ¬¡æ€§è¯Šæ–­è„šæœ¬ |
| `scripts/diagnose/diagnose_order.py` | 96 | | ä¸€æ¬¡æ€§è¯Šæ–­è„šæœ¬ |
| `$null` | 0 | | ç©ºæ–‡ä»¶ï¼Œåº”åˆ é™¤ |

## æµ‹è¯•

| æ–‡ä»¶ | è¡Œæ•° | æ ‡ç­¾ | è¯´æ˜Ž |
|------|------|------|------|
| `ExecutionView/backend/api/tests/test_parent_child_execution.py` | 324 | | çˆ¶å­æ‰§è¡Œé›†æˆæµ‹è¯• |
| `ExecutionView/backend/api/tests/test_algo_scheduler.py` | 319 | | ç®—æ³•è°ƒåº¦å™¨æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py` | 293 | | Bloomberg é€‚é…å™¨è·¯ç”±æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_batch_route_endpoints.py` | 289 | | æ‰¹é‡è·¯ç”±ç«¯ç‚¹æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_benchmark_engine.py` | 295 | | åŸºå‡†å¼•æ“Žæµ‹è¯• |
| `ExecutionView/backend/api/tests/test_compliance_service.py` | 142 | | åˆè§„æœåŠ¡æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_platform_data_access.py` | 231 | | è·¨åŸŸæ•°æ®è®¿é—®æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py` | 39 | | Bloomberg å‚ç…§æ•°æ®æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_realtime_gateway.py` | 103 | | å®žæ—¶æŽ¨é€ç½‘å…³æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_service_provider.py` | 69 | | æœåŠ¡å·¥åŽ‚æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_config_service.py` | 89 | | é…ç½®æœåŠ¡æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_auth_policy.py` | 66 | | è®¤è¯ç­–ç•¥æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_db_bootstrap.py` | 32 | | æ•°æ®åº“åˆå§‹åŒ–æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_connection_router.py` | 97 | | è¿žæŽ¥è·¯ç”±æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_marketview_router.py` | 143 | | MarketView è·¯ç”±æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_execution_history_router.py` | 131 | | æ‰§è¡ŒåŽ†å²è·¯ç”±æµ‹è¯• |
| `ExecutionView/backend/api/tests/test_projection_repositories.py` | 20 | | æŠ•å½±ä»“å‚¨æµ‹è¯• |
| `ExecutionView/frontend/src/services/realtime.test.ts` | 226 | | WebSocket å®¢æˆ·ç«¯æµ‹è¯• |
| `ExecutionView/frontend/src/modules/costview/lib/thresholds.test.ts` | 113 | | é˜ˆå€¼é€»è¾‘æµ‹è¯• |
| `ExecutionView/frontend/src/modules/costview/lib/report-state.test.ts` | 71 | | æŠ¥å‘ŠçŠ¶æ€æµ‹è¯• |
| `ExecutionView/frontend/src/modules/marketview/lib/workspace.test.ts` | 136 | | å·¥ä½œåŒºé€»è¾‘æµ‹è¯• |

---

## ç»Ÿè®¡æ‘˜è¦

| åˆ†ç±» | æ–‡ä»¶æ•° | ä»£ç è¡Œ | å æ¯” |
|------|--------|--------|------|
| æ ¸å¿ƒæŠ½è±¡ â­â­â­ | 7 | 4,732 | 6.5% |
| æ•°æ®å±‚ â­â­ | 21 | 3,734 | 5.1% |
| ä¸šåŠ¡é€»è¾‘ â­â­ | 46 | 16,855 | 23.0% |
| é›†æˆå±‚ â­ | 10 | 1,277 | 1.7% |
| é…ç½®/å·¥å…· â­ | 68 | 18,712 | 25.5% |
| Legacy/å¾…æ¸…ç† âš ï¸ | 13 | 1,053 | 1.4% |
| æµ‹è¯• | 21 | 2,957 | 4.0% |
| UI åŸºç¡€ç»„ä»¶ (ui/*) | ~40 | ~3,500 | 4.8% |
| å…¶ä»–ï¼ˆæœªåˆ—å‡ºçš„å°æ–‡ä»¶ï¼‰ | â€” | ~21,443 | 28.0% |
| **æ€»è®¡** | **331** | **73,263** | **100%** |

> **âš ï¸ è¶…é™æ–‡ä»¶æ±‡æ€»**ï¼ˆéœ€æ‹†åˆ†ï¼‰ï¼š`bloomberg_adapter.py`(2119), `batch-route-order-dialog.tsx`(1247), `SettingsBoard.tsx`(1102), `tca_query_service.py`(1082), `adapters.py`(936), `route-modify-dialogs.tsx`(893), `repositories.py`(866), `RouteTable.tsx`(866), `pipeline.py`(808), `fill_fetch.py`(773), `processed_fills_db.py`(685), `OrderTable.tsx`(681), `MarketViewModule.tsx`(795), `raw_fills_db.py`(516), `api.ts`(587), `import_excel_fills.py`(590), `auto_runner.py`(582), `service-manager.ps1`(519), `batch_route_service.py`(474), `route_plans.py`(491), `orders.py`(482), `marketview.py`(409), `costview.py`(434), `validate_raw_fills.py`(405)

