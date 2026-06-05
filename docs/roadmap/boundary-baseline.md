# Boundary Violations Baseline

Generated: 2026-06-03T10:26:55 | Total: **21**

> AI agent 与开发者按严重度分批修复。
> 修复后本文件需重新生成。

## CRITICAL (10) - Fix within 1 周内

### AP-04 (10)
- `backend\api\tests\boundaries\test_db_path_from_config.py`:0  hardcoded db path: data/raw_fills.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\ingestion\fill_fetch.py`:0  hardcoded db path: Fetched {len(fills)} fills, upserted {rows_upserted} to raw_fills.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\processing\validate_raw_fills.py`:0  hardcoded db path: No dates found in raw_fills.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\storage\archiver.py`:0  hardcoded db path: {db_name}.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\storage\backup.py`:0  hardcoded db path: regime.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\storage\connection.py`:0  hardcoded db path: regime.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\storage\schema\migration_framework.py`:0  hardcoded db path: regime.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\storage\schema\migrations\apply.py`:0  hardcoded db path: CostView/data/regime.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `DataPipeline\analysis\regime\schema.py`:0  hardcoded db path: regime.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]
- `CostView\src\__main__.py`:0  hardcoded db path: (Legacy) Ingest Excel files -> raw_fills.db
  - Fix: 改用 DataPipeline.config.Config.DB_PATHS[...]

## HIGH (11) - Fix within 2 周内

### AP-05 (11)
- `backend\api\routers\broker.py`:0  endpoint 'get_trader_info' (line 23) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\connection.py`:0  endpoint 'get_connection_status' (line 59) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\database.py`:0  endpoint 'get_database_overview' (line 184) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\debug.py`:0  endpoint 'get_round_lot_sizes' (line 20) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\execution_history.py`:0  endpoint 'get_fill_history' (line 99) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\market_broker_mapping.py`:0  endpoint 'update_selection' (line 118) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\orders_crud.py`:0  endpoint 'get_orders_status' (line 27) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\orders_execution.py`:0  endpoint 'create_parent_execution' (line 100) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\orders_handoff.py`:0  endpoint 'get_active_candidate_handoff' (line 46) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\routes.py`:0  endpoint 'get_routes' (line 23) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
- `backend\api\routers\route_plans.py`:0  endpoint 'list_route_plans' (line 153) does not return ApiResponse
  - Fix: 改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)
