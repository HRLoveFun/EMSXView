# å…¥å£ç‚¹æ¸…å•

> **æ•°æ®æ¥æº**ï¼š05a (`__main__` å—) / 05b (CLI æ¡†æž¶) / 05c (package entry_points) / 05d (Web å…¥å£) / 05e (README å‘½ä»¤) / 05f (Shell è„šæœ¬) / 05g (å®šæ—¶è°ƒåº¦) / 05h (git ä¿®æ”¹é¢‘çŽ‡) / 05_real_entrypoints (åˆ†ç±»ç»“æžœ) / 05_reverse_trace (å¤–éƒ¨è§¦å‘)
>
> **æ€»è§ˆ**ï¼šEMSX é¡¹ç›®æœ‰ **4 ç±»å…¥å£**ï¼šWeb APIï¼ˆFastAPI 75+ è·¯ç”±ï¼‰ã€CLIï¼ˆ`python <script>`ï¼‰ã€Shell åŒ…è£…ï¼ˆ`.bat`/`.ps1`ï¼‰ã€åŽå°è°ƒåº¦ï¼ˆ`schedule` åº“ + Windows Task Schedulerï¼‰ã€‚æ—  `console_scripts` æˆ– `entry_points` å£°æ˜Žï¼ˆ05c ä¸ºç©ºï¼‰ï¼Œæ‰€æœ‰å…¥å£é€šè¿‡ `python <script>` æˆ– Shell è„šæœ¬é—´æŽ¥è°ƒç”¨ã€‚

---

## ä¸»å…¥å£ï¼ˆExternal â€” ç”¨æˆ·/ç³»ç»Ÿä¼šè°ƒç”¨ï¼‰

### 1. Web æœåŠ¡: `ExecutionView/backend/api/main.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š`python start_server.py` æˆ– `start-services.bat`
- **FastAPI å®žä¾‹**ï¼š`app = FastAPI(title="EMSX Trading API")` (L288)
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`uvicorn.run("main:app", host, port)` â†’ æ³¨å†Œ 75+ è·¯ç”± â†’ Bloomberg å®žæ—¶è®¢é˜…
- **å¯åŠ¨ç”Ÿå‘½å‘¨æœŸ**ï¼š
  1. `load_dotenv()` åŠ è½½ `.env`
  2. `Settings` å•ä¾‹åˆå§‹åŒ–
  3. `app.on_event("startup")` â†’ `bloomberg_adapter.connect()` (async)
  4. åŽå°çº¿ç¨‹å¯åŠ¨ï¼šemsx-subscription / mktdata-subscription
- **è¯æ®**ï¼š05a (L384 `__main__` å— 8 è¡Œ), 05d (1 ä¸ªæ­£å¼ FastAPI å…¥å£), 05e (QUICKSTART.md + docs/dev-guide.md), 05f (æ‰€æœ‰ .bat/.ps1 æœ€ç»ˆæŒ‡å‘æ­¤æ–‡ä»¶), 05h (git ä¿®æ”¹ 9 æ¬¡ï¼Œä»£ç æ–‡ä»¶ä¸­æœ€é«˜é¢‘)
- **å¥åº·æ£€æŸ¥**ï¼š`GET /api/health`ï¼ˆç”± `service-manager.ps1` å’Œ Docker deploy.sh è½®è¯¢ï¼‰

### 2. Web å¤‡ç”¨å¯åŠ¨å™¨: `ExecutionView/backend/api/start_server.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š`python start_server.py`ï¼ˆå›ºå®š host=0.0.0.0:3000ï¼‰
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`uvicorn.run("main:app", ...)`
- **ä¸Ž #1 çš„å…³ç³»**ï¼šåŠŸèƒ½é‡å ï¼›`start_server.py` æ˜¯ `.bat`/`.ps1` çš„å®žé™…è°ƒç”¨ç›®æ ‡ï¼ˆè§ `service-manager.ps1` L52 é…ç½®ï¼‰
- **è¯æ®**ï¼š05a (L15 `__main__` å— 14 è¡Œ), 05f (`service-manager.ps1` é…ç½® `Script = "ExecutionView\backend\api\start_server.py"`)

### 3. Shell å¤åˆå…¥å£: `start-services.bat`

- **å¦‚ä½•è¿è¡Œ**ï¼šåŒå‡» / å‘½ä»¤è¡Œ `start-services.bat`
- **å†…éƒ¨è°ƒç”¨é“¾**ï¼š
  1. åŽç«¯ï¼š`cd ExecutionView\backend\api && python start_server.py` (port 3000)
  2. å‰ç«¯ï¼š`cd ExecutionView\frontend && npm run dev` (port 5173)
- **è¯æ®**ï¼š05f (L52/L69 æ˜¾å¼å‘½ä»¤), 05e (QUICKSTART.md é¦–æŽ¨å…¥å£)

### 4. Shell æ ¸å¿ƒè°ƒåº¦å™¨: `scripts/service-manager.ps1`

- **å¦‚ä½•è¿è¡Œ**ï¼š`powershell -File service-manager.ps1 <start|stop|restart|status|logs|kill>`
- **æ ¸å¿ƒèƒ½åŠ›**ï¼šç«¯å£å†²çªæ£€æµ‹ã€å¥åº·æ£€æŸ¥ã€åŒæ­¥å¯åœã€graceful shutdown
- **æ‰€æœ‰ .bat çš„å§”æ‰˜ç›®æ ‡**ï¼š`start-all.bat` â†’ `service-manager.ps1 start`ï¼ŒåŒç† stop/restart/check-status
- **è¯æ®**ï¼š05f (6 ä¸ª .bat å…¨éƒ¨å§”æ‰˜æ­¤è„šæœ¬), 05e (QUICKSTART.md æåŠ)

### 5. CLI: `CostView/src/__main__.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š`python -m src [options]`
- **æ”¯æŒå‚æ•°**ï¼š`--fetch-auto`, `--process`, `--aggregate`, `--pipeline`, `--query {fills|raw-fills|log|orders|tickers|summary}`, `--schedule`, `--schedule-once`, `--schedule-time`, `--rebuild-processed`, `--rebuild-aggregated`, `--status`, `--force`, `--bdib`, `--db-access`, `--process-date`, `--process-range`
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`run_full_pipeline()` / `FillFetch.fetch_range_aggregated()` / `QueryEngine.query_*()` ç­‰
- **è¯æ®**ï¼š05a (L327 `__main__`, main() å‡½æ•° 250+ è¡Œ), 05b (argparse 30+ å‚æ•°), 05e (CostView/README.md åˆ—ä¸¾ `python -m src` 6 ç§ç”¨æ³•)
- **åˆ†å±‚è°ƒç”¨**ï¼š
  ```
  __main__.py â†’ pipeline.run_full_pipeline()
                           â†’ run_process() â†’ processed_fills_db
                           â†’ run_aggregate() â†’ bdib_daily_summary
                           â†’ run_order_labels()
  ```

### 6. CLI: `CostView/src/fill_fetch.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š`python -m src.fill_fetch` æˆ– `python -m src --fetch`
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`FillFetch` ç±» â†’ Bloomberg EMSX API æŠ“å– fill æ•°æ®
- **è¯æ®**ï¼š05a (L1136 `__main__`), 05b (argparse), è¢« `__main__.py` é€šè¿‡ `--fetch` è°ƒç”¨

### 7. å®šæ—¶è°ƒåº¦: `CostView/scripts/daily_update.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š
  - äº¤äº’å¼ï¼š`python daily_update.py`ï¼ˆè¿›å…¥ schedule å¾ªçŽ¯ï¼Œé»˜è®¤ 18:00ï¼‰
  - å•æ¬¡ï¼š`python daily_update.py --once`ï¼ˆWindows Task Scheduler è°ƒç”¨ï¼‰
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`run_daily_pipeline()` â†’ fetch + process + BDIB + manifest
- **å¤–éƒ¨è§¦å‘**ï¼šWindows Task Schedulerï¼ˆé€šè¿‡ `install_scheduler.py` æ³¨å†Œï¼‰
- **è¯æ®**ï¼š05a (L186 `__main__`), 05b (argparse), 05g (schedule åº“ + Windows Task Scheduler), 05e (CostView/README.md)

### 8. Windows è®¡åˆ’ä»»åŠ¡å®‰è£…å™¨: `CostView/scripts/install_scheduler.py`

- **å¦‚ä½•è¿è¡Œ**ï¼š`python install_scheduler.py [--time 08:30] [--uninstall] [--status]`
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`schtasks.exe /Create /TN "CostView_DailyUpdate" /TR "python daily_update.py --once"`
- **è¯æ®**ï¼š05a (L130 `__main__`), 05g (cron/schedule åŒ¹é…), 05e (README æ–‡æ¡£)

### 9. Docker éƒ¨ç½²: `scripts/deploy/deploy.sh`

- **å¦‚ä½•è¿è¡Œ**ï¼š`./deploy.sh start|stop|restart|status|logs|update|backup`
- **å†…éƒ¨è°ƒç”¨**ï¼š`docker compose up -d` â†’ Nginx(80) åä»£ Backend(3000)
- **å¥åº·æ£€æŸ¥**ï¼š`curl http://localhost:3000/api/health`
- **è¯æ®**ï¼š05f (å”¯ä¸€ .sh æ–‡ä»¶)

### 10. MCP çŸ¥è¯†æœåŠ¡å™¨: `scripts/mcp/knowledge-server.py`

- **å¦‚ä½•è¿è¡Œ**ï¼šç”± AI å®¢æˆ·ç«¯é€šè¿‡ stdio åè®®è°ƒç”¨ï¼ˆéžæ‰‹åŠ¨å¯åŠ¨ï¼‰
- **æ ¸å¿ƒè°ƒç”¨**ï¼š`mcp.run(transport="stdio")`
- **è¯æ®**ï¼š05a (L317 `__main__`)

---

## æ¬¡è¦å…¥å£ï¼ˆæ—¥å¸¸è¿ç»´ï¼ŒæŒ‰éœ€è°ƒç”¨ï¼‰

### CostView æ•°æ®å·¥å…·

| # | è„šæœ¬ | å¦‚ä½•è¿è¡Œ | æ ¸å¿ƒè°ƒç”¨ | è¯æ® |
|---|---|---|---|---|
| 11 | `CostView/src/daily_metrics_calculator.py` | `python daily_metrics_calculator.py --date 20260115` æˆ– `--all` | `CalculateDailyMetrics.run_for_date()` | 05a, 05b |
| 12 | `CostView/src/validate_raw_fills.py` | `python validate_raw_fills.py [options]` | `main()` å®Œæ•´ CLI é€»è¾‘ | 05a |
| 13 | `CostView/src/secure_config.py` | `python secure_config.py --validate` æˆ– `--setup` | `SecureConfigManager` äº¤äº’å¼é…ç½® | 05a, 05b |
| 14 | `CostView/scripts/backfill_raw_bdib.py` | `python backfill_raw_bdib.py [options]` | `main()` â€” 698 è¡Œå¤§è„šæœ¬ | 05a, 05b |
| 15 | `CostView/scripts/backfill_bdib_history.py` | `python backfill_bdib_history.py --lookback 25 [--dry-run]` | `run_backfill()` | 05a, 05b |
| 16 | `CostView/scripts/backfill_regime.py` | `python backfill_regime.py` | `main()` | 05a |
| 17 | `CostView/scripts/fetch_macro_calendar.py` | `python fetch_macro_calendar.py --start --end` | `main()` | 05a, 05b |
| 18 | `CostView/scripts/run_attribution.py` | `python run_attribution.py --inspect --by broker algo` | `main()` | 05a, 05b, 05e (docs/RESEARCH_NOTES æåŠ) |
| 19 | `CostView/scripts/seed_macro_events.py` | `python seed_macro_events.py` | `main()` | 05a |

### CostView Regime ç»´æŠ¤

| # | è„šæœ¬ | æ ¸å¿ƒè°ƒç”¨ | è¯æ® |
|---|---|---|---|
| 20 | `CostView/src/regime/migrations/apply.py` | `main()` â€” regime.db è¿ç§» | 05a, 05b |
| 21 | `CostView/src/regime/sync_macro_calendar.py` | CSV â†’ ref_macro_event_calendar | 05a, 05b |
| 22 | `CostView/src/regime/sync_macro_event_dict.py` | JSON â†’ ref_macro_event_dict | 05a, 05b |
| 23 | `CostView/src/regime/sync_market_mapping.py` | JSON â†’ ref_market_mapping | 05a, 05b |
| 24 | `CostView/src/regime/validate_macro_calendar.py` | æ ¡éªŒ macro_calendar.csv | 05a, 05b |

### é¡¹ç›®çº§è¿ç»´è„šæœ¬

| # | è„šæœ¬ | å¦‚ä½•è¿è¡Œ | æ ¸å¿ƒè°ƒç”¨ | è¯æ® |
|---|---|---|---|---|
| 25 | `scripts/workflow/auto_runner.py` | `python auto_runner.py run-step/check-step/run-all` | `main()` 757 è¡Œ | 05a, 05b |
| 26 | `scripts/workflow/validate_phase_gate.py` | `python validate_phase_gate.py --mode` | `main()` | 05a, 05b |
| 27 | `scripts/workflow/sync_execution_status.py` | `python sync_execution_status.py` | `main()` | 05a, 05b |
| 28 | `scripts/workflow/generate_handoff_snapshot.py` | `python generate_handoff_snapshot.py` | `main()` | 05a, 05b |
| 29 | `scripts/workflow/collect_ci_status.py` | `python collect_ci_status.py` | `main()` | 05a, 05b |
| 30 | `scripts/import_excel_fills.py` | `python import_excel_fills.py --dry-run/--execute` | `main()` 951 è¡Œ | 05a, 05b |
| 31 | `scripts/fetch_and_inspect.py` | `python fetch_and_inspect.py --team` | `run_full_inspection()` | 05a, 05b |
| 32 | `scripts/sync-metrics.py` | `python sync-metrics.py` | `main()` | 05a |
| 33 | `scripts/run_attribution_notebook.py` | `python run_attribution_notebook.py` | papermill æ‰§è¡Œ | 05a |

### Git Hooksï¼ˆIDE Agent è°ƒç”¨ï¼‰

| # | è„šæœ¬ | è§¦å‘æ—¶æœº | è¡Œä¸º | è¯æ® |
|---|---|---|---|---|
| 34 | `scripts/hooks/session-context.py` | SessionStart | æ³¨å…¥çŸ¥è¯†åº“æ‘˜è¦åˆ°ä¸Šä¸‹æ–‡ | 05a |
| 35 | `scripts/hooks/session-summary.py` | SessionEnd | è®°å½•ä¼šè¯æ‘˜è¦ | 05a |
| 36 | `scripts/hooks/log-change.py` | æ–‡ä»¶å˜æ›´ | è®°å½•å˜æ›´äº‹ä»¶ | 05a |

---

## è°ƒè¯•å…¥å£ï¼ˆå¼€å‘è€…ä¸´æ—¶ä½¿ç”¨ï¼Œä¸ç®—æ­£å¼å…¥å£ï¼‰

| è„šæœ¬ | åŽŸå›  | è¯æ® |
|---|---|---|
| `CostView/examples/secure_uuid_example.py` | ç¤ºä¾‹ä»£ç  | 05_real_entrypoints: âŒ |
| `scripts/diagnose/diagnose_exchange_ticker_issue.py` | ä¸€æ¬¡æ€§è¯Šæ–­ | 05_real_entrypoints: âŒ |
| `scripts/diagnose/diagnose_odd_lot.py` | è°ƒè¯•å…¥å£ï¼Œè°ƒç”¨ `test_api()` | 05_real_entrypoints: âŒ |
| `scripts/diagnose/diagnose_orders_display.py` | ä¸€æ¬¡æ€§è¯Šæ–­ | 05_real_entrypoints: âŒ |
| `CostView/tests/test_*.py` (5 ä¸ª) | æµ‹è¯•æ–‡ä»¶ | 05_real_entrypoints: âŒ |
| `CostView/_archive/` (4 ä¸ª) | å½’æ¡£è„šæœ¬ | 05_real_entrypoints: âŒ |
| `scripts/_archive/` (4 ä¸ª) | å½’æ¡£è„šæœ¬ | 05_real_entrypoints: âŒ |
| `CostView/test_comprehensive.py` | æµ‹è¯•æ–‡ä»¶ | 05_real_entrypoints: âŒ |
| `CostView/test_pipeline_guards.py` | æµ‹è¯•æ–‡ä»¶ | 05_real_entrypoints: âŒ |

---

## API è·¯ç”±æ¸…å•ï¼ˆFastAPI, 75+ ç«¯ç‚¹ï¼‰

åŽç«¯å…¥å£ï¼š`ExecutionView/backend/api/main.py`ï¼ˆL288: `app = FastAPI(title="EMSX Trading API")`ï¼‰

### è¿žæŽ¥ä¸Žå¥åº·ï¼ˆ`routers/connection.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ | è¯´æ˜Ž |
|---|---|---|
| GET | `/` | æ ¹è·¯å¾„ |
| GET | `/api/health` | å¥åº·æ£€æŸ¥ï¼ˆservice-manager + Docker è½®è¯¢ï¼‰ |
| GET | `/api/connection` | è¿žæŽ¥çŠ¶æ€ |
| GET | `/api/startup-status` | å¯åŠ¨é˜¶æ®µè¯Šæ–­ |
| POST | `/api/connection/reconnect` | Bloomberg é‡è¿ž |

### è®¤è¯ï¼ˆ`routers/auth.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| POST | `/api/auth/login` |

### è®¢å•ä¸Žæ‰§è¡Œï¼ˆ`routers/orders.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ | è¯´æ˜Ž |
|---|---|---|
| GET | `/api/orders/status` | è®¢å•çŠ¶æ€æ‘˜è¦ |
| GET | `/api/orders` | è®¢å•åˆ—è¡¨ |
| POST | `/api/orders/modify` | ä¿®æ”¹è®¢å• |
| POST | `/api/orders/route` | è·¯ç”±è®¢å• |
| POST | `/api/orders/batch-update` | æ‰¹é‡æ›´æ–° |
| POST | `/api/orders/batch-route` | æ‰¹é‡è·¯ç”± |
| GET | `/api/orders/refresh` | åˆ·æ–°ç¼“å­˜ |
| POST | `/api/orders/{order_id}/cancel` | å–æ¶ˆè®¢å• |
| POST | `/api/executions` | æ‰§è¡Œè¯¦æƒ… |
| POST | `/api/executions/{parent_id}/command` | æ‰§è¡ŒæŒ‡ä»¤ |
| GET | `/api/executions/{parent_id}` | å•ä¸ªæ‰§è¡Œ |
| GET | `/api/executions` | æ‰§è¡Œåˆ—è¡¨ |
| GET | `/api/executions/handoff/candidates` | æ‰‹é€’äº¤æŽ¥å€™é€‰ |
| POST | `/api/executions/handoff/post-trade` | ç›˜åŽäº¤æŽ¥ |

### è·¯ç”±ï¼ˆ`routers/routes.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/routes` |
| POST | `/api/routes/cancel` |
| POST | `/api/routes/modify` |
| POST | `/api/routes/batch-modify` |
| GET | `/api/routes/diagnose-strategy-rate` |
| GET | `/api/routes/reference-enums` |

### ç»çºªå•†ï¼ˆ`routers/broker.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/trader-info` |
| GET | `/api/asset-class` |
| GET | `/api/broker-strategies` |
| GET | `/api/broker-strategy-info` |
| GET | `/api/brokers` |
| GET | `/api/broker-algorithms` |
| POST | `/api/broker-algorithms/refresh` |
| GET | `/api/broker-algorithms/status` |
| GET | `/api/broker-recommendations` |

### å¸‚åœºè§†å›¾ï¼ˆ`routers/marketview.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/marketview/snapshot` |
| GET | `/api/marketview/intraday-features` |
| POST | `/api/marketview/handoff/execution` |

### ç»çºªå•†-å¸‚åœºæ˜ å°„ï¼ˆ`routers/market_broker_mapping.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/market-broker-mapping` |
| PUT | `/api/market-broker-mapping/selection` |
| POST | `/api/market-broker-mapping/unlock` |
| PUT | `/api/market-broker-mapping/roster` |

### è·¯ç”±è®¡åˆ’ï¼ˆ`routers/route_plans.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET/POST | `/api/route-plans` |
| GET/PUT/DELETE | `/api/route-plans/{plan_id}` |
| POST | `/api/route-plans/{plan_id}/test-match` |
| POST | `/api/route-engine/apply/{order_id}` |
| GET | `/api/sub-order-proposals` |
| POST | `/api/sub-order-proposals/{id}/confirm` |
| POST | `/api/sub-order-proposals/batch-confirm` |
| POST | `/api/sub-order-proposals/{id}/reject` |

### TCA / CostViewï¼ˆ`routers/costview.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ | è¯´æ˜Ž |
|---|---|---|
| POST | `/api/tca/analyze` | TCA åˆ†æž |
| POST | `/api/tca/scorecard` | TCA è®°åˆ†å¡ |
| POST | `/api/tca/trigger-update` | **è§¦å‘ CostView ç®¡é“æ›´æ–°**ï¼ˆå­è¿›ç¨‹ï¼‰ |
| GET | `/api/tca/update-status/{job_id}` | ç®¡é“è¿›åº¦æŸ¥è¯¢ |
| POST | `/api/tca/recommendations/pin` | å›ºå®š TCA å»ºè®® |
| GET | `/api/tca/handoff/post-trade/{order_id}` | ç›˜åŽ TCA äº¤æŽ¥ |
| GET | `/api/costview/regime-distribution` | å¸‚åœºçŠ¶æ€åˆ†å¸ƒ |

### æ•°æ®åº“ç®¡ç†ï¼ˆ`routers/database.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/db/overview` |
| GET | `/api/db/{key}/summary` |
| GET | `/api/db/{key}/integrity` |
| GET | `/api/db/{key}/tables/{table}/schema` |
| GET | `/api/db/{key}/tables/{table}/sample` |
| POST | `/api/db/update` |
| GET | `/api/db/update-status/{job_id}` |

### æ‰§è¡ŒåŽ†å²ï¼ˆ`routers/execution_history.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/execution-history/fills` |
| GET | `/api/execution-history/orders` |
| GET | `/api/execution-history/routes` |

### è°ƒè¯•ï¼ˆ`routers/debug.py`ï¼‰

| æ–¹æ³• | è·¯å¾„ |
|---|---|
| GET | `/api/debug/round-lot-sizes` |
| POST | `/api/debug/query-round-lot` |

### WebSocket

| ç±»åž‹ | è·¯å¾„ | è¯´æ˜Ž |
|---|---|---|
| WebSocket | `/ws/orders` | å®žæ—¶è®¢å•æŽ¨é€ |

---

## å®šæ—¶ä»»åŠ¡

### è¿›ç¨‹å†…è°ƒåº¦

| è§¦å‘æ–¹å¼ | æ‰€åœ¨æ–‡ä»¶ | è¯´æ˜Ž |
|---|---|---|
| `schedule` åº“ | `CostView/scripts/daily_update.py` (L174) | æ¯å¤© `--time`ï¼ˆé»˜è®¤ 18:00ï¼‰æ‰§è¡Œ `run_daily_pipeline()` |
| `asyncio.create_task` | `ExecutionView/backend/api/main.py` (L277) | app å¯åŠ¨æ—¶å¼‚æ­¥è¿žæŽ¥ Bloomberg |
| `threading.Thread` | `bloomberg_adapter.py` (L447) | Bloomberg è®¢å•è®¢é˜…åŽå°çº¿ç¨‹ |
| `threading.Thread` | `bloomberg_adapter.py` (L455) | Bloomberg è¡Œæƒ…è®¢é˜…åŽå°çº¿ç¨‹ |
| `threading.Thread` | `_pipeline_jobs.py` (L212) | CostView ç®¡é“å­è¿›ç¨‹ï¼Œç”± `/api/tca/trigger-update` è§¦å‘ |
| `ThreadPoolExecutor` | `CostView/src/pipeline.py` (L20) | å¢žé‡å¤„ç†å¹¶è¡Œä»»åŠ¡æ±  |

### å¤–éƒ¨è°ƒåº¦

| è§¦å‘æ–¹å¼ | æ–‡ä»¶ | è¯´æ˜Ž |
|---|---|---|
| Windows Task Scheduler | `CostView/scripts/install_scheduler.py` | `schtasks.exe` æ³¨å†Œ `python daily_update.py --once` |
| Docker Compose | `scripts/deploy/deploy.sh` | `docker compose up -d`ï¼ŒNginx:80 â†’ Backend:3000 |
| Windows Task Scheduler | `scripts/cleanup-logs.ps1` | æ—¥å¿—æ¸…ç†ï¼Œå»ºè®®æ¯æ—¥ 3amï¼ˆéœ€æ‰‹åŠ¨æ³¨å†Œï¼‰ |

---

## é…ç½®å…¥å£

### æ ¸å¿ƒé…ç½®

| æ–‡ä»¶ | æŠ€æœ¯ | è¯´æ˜Ž | è¯æ® |
|---|---|---|---|
| `ExecutionView/backend/api/config.py` | `os.getenv` + æ ¡éªŒ | åŽç«¯å…¨å±€é…ç½®å•ä¾‹ | 05e (CLAUDE.md) |
| `.env` | `load_dotenv()` | æ´»è·ƒçŽ¯å¢ƒå˜é‡ (main.py:29-30) | 05e |
| `ExecutionView/backend/.env.example` | â€” | åŽç«¯é…ç½®æ¨¡æ¿ | 05e |
| `ExecutionView/frontend/.env` | Vite env | å‰ç«¯ API åœ°å€ç­‰ | â€” |
| `CostView/.env.example` | â€” | CostView é…ç½®æ¨¡æ¿ | â€” |

### CostView ç®¡é“é…ç½®

| æ–‡ä»¶ | æŠ€æœ¯ | è¯´æ˜Ž | è¯æ® |
|---|---|---|---|
| `CostView/src/processing_config.py` | `ProcessingConfig` ç±» | ä¸­å¿ƒåŒ–é…ç½®ï¼šç›®å½•/DB/æ—¥å¿—/BDIB å‚æ•° | 05e (README) |
| `CostView/src/secure_config.py` | UUID + çŽ¯å¢ƒå˜é‡/JSON | Bloomberg EMSX å‡­æ®ç®¡ç† | 05a (argparse --setup/--validate) |
| `CostView/src/attribution/config.py` | SQLite | å½’å› åˆ†æžé…ç½® | â€” |
| `CostView/src/regime/config.py` | SQLite | å¸‚åœºçŠ¶æ€é˜ˆå€¼é…ç½® | â€” |

### æ•°æ®å…¥å£

| å…¥å£ | é…ç½®æ–¹å¼ | è¯´æ˜Ž |
|---|---|---|
| Excel æ–‡ä»¶ç›®å½• | `Config.EXCEL_DIR` | fill æ•°æ®æºï¼ˆ`import_excel_fills.py`ï¼‰ |
| `raw_fills.db` | `Config.RAW_FILLS_DB` | åŽŸå§‹ fill æ•°æ®åº“ |
| `processed_fills.db` | `Config.PROCESSED_FILLS_DB` | å¤„ç†åŽ fill æ•°æ®åº“ |
| `regime.db` | `Config.REGIME_DB` | å¸‚åœºçŠ¶æ€æ•°æ®åº“ |
| Bloomberg API | `Config.BLOOMBERG_HOST/PORT` | å®žæ—¶æ•°æ®+äº¤æ˜“ç½‘å…³ |

---

## è°ƒç”¨é“¾æ€»å›¾

```
ç”¨æˆ· â”€â”€åŒå‡»â”€â”€â–¶ start-services.bat
                â”‚
                â”œâ”€â–¶ python ExecutionView/backend/api/start_server.py
                â”‚       â””â”€â–¶ uvicorn main:app (FastAPI, :3000)
                â”‚            â”œâ”€â–¶ startup: bloomberg_adapter.connect()
                â”‚            â”œâ”€â–¶ threads: emsx-subscription, mktdata-subscription
                â”‚            â””â”€â–¶ 75+ API routes + /ws/orders

                â””â”€â–¶ npm run dev (ExecutionView/frontend/, :5173)
                        â””â”€â–¶ App.tsx â†’ services/api.ts â†’ :3000

ç”¨æˆ· â”€â”€åŒå‡»â”€â”€â–¶ é‡å¯æœåŠ¡.bat
                â””â”€â–¶ scripts/service-manager.ps1 restart
                        â”œâ”€â–¶ stop (kill :3000, :5173)
                        â””â”€â–¶ start (åŒä¸Š)

å®šæ—¶ â”€â”€Windows Task Schedulerâ”€â”€â–¶ python daily_update.py --once
                                        â””â”€â–¶ run_daily_pipeline()
                                              â”œâ”€â–¶ FillFetch â†’ raw_fills.db
                                              â”œâ”€â–¶ pipeline.run_process() â†’ processed_fills.db
                                              â”œâ”€â–¶ daily_metrics_calculator â†’ bdib_daily_summary
                                              â””â”€â–¶ manifest å†™å…¥

å¼€å‘ â”€â”€CLIâ”€â”€â–¶ python -m src [options]
                â”œâ”€â–¶ --fetch-auto â†’ FillFetch.fetch_range_aggregated()
                â”œâ”€â–¶ --pipeline â†’ run_full_pipeline()
                â”œâ”€â–¶ --query â†’ QueryEngine.query_*()
                â””â”€â–¶ --schedule â†’ schedule.every().day().do()

AI â”€â”€stdioâ”€â”€â–¶ scripts/mcp/knowledge-server.py
                â””â”€â–¶ mcp.run(transport="stdio")

è¿ç»´ â”€â”€bashâ”€â”€â–¶ scripts/deploy/deploy.sh start
                â””â”€â–¶ docker compose up (Nginx:80 â†’ Backend:3000)
```

---

## ä¿®æ”¹é¢‘çŽ‡æŽ’åï¼ˆ05hï¼Œè¿‘ 3 ä¸ªæœˆï¼‰

| æŽ’å | æ–‡ä»¶ | æ¬¡æ•° | è§’è‰² |
|---|---|---|---|
| 1 | `.github/knowledge/iteration-log.md` | 20 | çŸ¥è¯†åº“ï¼ˆè‡ªåŠ¨æ›´æ–°ï¼‰ |
| 7 | **`ExecutionView/backend/api/main.py`** | 9 | **åŽç«¯è£…é…å…¥å£** |
| 11 | **`ExecutionView/backend/api/services/bloomberg_adapter.py`** | 7 | Bloomberg é€‚é…å™¨æž¢çº½ |
| 15 | **`ExecutionView/frontend/src/App.tsx`** | 6 | **å‰ç«¯å£³å…¥å£** |
| 14 | `ExecutionView/frontend/src/services/api.ts` | 6 | å‰ç«¯ API å±‚ |
| 19 | `CostView/src/pipeline.py` | 5 | CostView ç®¡çº¿æ ¸å¿ƒ |

> `main.py`(9æ¬¡) ç¡®è®¤æœ€æ ¸å¿ƒåŽç«¯å…¥å£ï¼›`App.tsx`(6æ¬¡) ç¡®è®¤å”¯ä¸€å‰ç«¯å£³å…¥å£ï¼›`bloomberg_adapter.py`(7æ¬¡) éžå…¥å£ä½†æ˜¯è¢«è°ƒç”¨æœ€å¤šçš„æœåŠ¡å±‚æž¢çº½ã€‚

