"""EMSXView 只读数据访问层 — schema 子包。

列常量的只读裁剪副本（原 `columns.py`）已随 2026-09-10 清理移除 —— schema 由唯一写入方
独立仓库 EMSXDataPipeline 维护；读侧库/表常量统一从 `data_access/config.py::Config` 获取。
"""
