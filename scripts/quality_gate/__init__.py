"""EMSXView 质量门禁框架（Quality Gate）。

统一承载两类规则的检测 / 基线 / 报告 / hook 集成：

- **AP-xx 契约违规**（确定性，block 门禁）：包装既有 ``audit_*.py`` 审计脚本，
  任何违规立即阻断——与既有 pre-commit 行为一致
- **OE-xx 过度工程**（启发式，guard 门禁）：自研 AST 检测器，
  基线演进——新增阻断 / 存量放行 / 修复正向提示

用法::

    python scripts/quality_gate.py                 # 全量扫描
    python scripts/quality_gate.py --report        # 全量扫描 + Markdown 报告
    python scripts/quality_gate.py --staged        # 增量模式（pre-commit 调用，文件列表走 stdin）
    python scripts/quality_gate.py --suppress <fp> --note "理由"   # 人工豁免误报
"""
