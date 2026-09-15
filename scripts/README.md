# EMSXView Scripts Directory

Quick-launch batch files for local development workflows.

## Directory Layout

```
scripts/
├── ci/                     # CI 专用替身
│   └── blpapi_stub/            Bloomberg API 桩（无 blpapi 许可的 CI 环境）
├── cleanup/                # 代码清理门禁（CL-xx 冗余 / PF-xx 性能热点）
├── quality_gate/           # 质量门禁（AP-xx 边界契约 / OE-xx 过度工程）
├── ops/                    # Operational scripts (service management, data ops)
│   ├── service-manager.ps1     Primary service lifecycle manager
│   └── cleanup-logs.ps1        Log rotation / purge
│
├── devtools/               # Developer tooling
│   ├── export-localstorage-cache.js  Browser storage cache export
│   └── wt-*.ps1                Git worktree 多任务并行工具集（ADR-0700）
│
├── deploy/                 # Deployment & environment setup
├── diagnose/               # Diagnostic / troubleshooting scripts
├── hooks/                  # Git hooks 辅助脚本
├── mcp/                    # MCP knowledge server
├── reports/                # 报告生成器（generate_tca_report.py；输出受 .gitignore 管理）
│
├── *.bat                   # Root-level quick-launch shortcuts
│   ├── start-all.bat            Start all services
│   ├── stop-all.bat             Stop all services
│   ├── restart-all.bat          Restart all services
│   └── check-status.bat         Check service health
│
└── audit_*.py              # 契约/数据路径/文档漂移/下划线访问审计（CI 边界门禁调用）
```

## Quick Reference

| Use case                          | Command                                      |
|-----------------------------------|----------------------------------------------|
| Start all services                | `start-all.bat` or `ops\service-manager.ps1` |
| Clean log files                   | `ops\cleanup-logs.ps1`                       |
| Create desktop shortcuts          | `deploy\create-desktop-shortcut.ps1`          |
| Check startup status              | `diagnose\check-startup-status.ps1`          |
| 质量门禁（全量 + 债务报告）        | `python quality_gate.py --report`            |
| 清理门禁（冗余 / 性能热点）        | `python cleanup.py --report`                 |
| 模块边界审计（CI 同款）            | `python audit_cross_imports.py`              |
