#!/usr/bin/env bash
# Pre-commit 提示（非阻断）
# 当检测到某些文件变更，提示同步相关文档
# 接入: 复制到 .git/hooks/pre-commit，或用 husky/lefthook 配置

set +e
nudges=()

# 检测 1: 新增/修改 module.registry.ts
if git diff --cached --name-only 2>/dev/null | grep -q "module.registry.ts"; then
    nudges+=("📝 module.registry.ts 变更 → 检查 .codebuddy/rules/module-boundary.md §1 是否需更新")
fi

# 检测 2: 新增 router 文件
if git diff --cached --name-only --diff-filter=A 2>/dev/null | grep -q "backend/api/routers/.*\.py"; then
    nudges+=("📝 新增 router → 确认走 _register_optional 模式 + ApiResponse 包装")
fi

# 检测 3: 新增 CostView/src 文件
if git diff --cached --name-only --diff-filter=A 2>/dev/null | grep -q "CostView/src/.*\.py"; then
    nudges+=("📝 CostView/src 新文件 → 是否应改走 DataPipeline/?")
fi

# 检测 4: 新增 platform_data/adapters 文件
if git diff --cached --name-only --diff-filter=A 2>/dev/null | grep -q "platform_data/adapters/.*\.py"; then
    nudges+=("📝 新增 platform_data 适配器 → 更新 .codebuddy/rules/module-boundary.md §2.3 公开/私有分界表")
fi

# 检测 5: 新增 ADR
if git diff --cached --name-only --diff-filter=A 2>/dev/null | grep -q "docs/spec/adr/[0-9]*.md"; then
    nudges+=("📝 新增 ADR → 同步更新 docs/spec/memory.md §2 索引表")
fi

# 检测 6: 新增反模式
if git diff --cached --name-only 2>/dev/null | grep -q "anti-patterns.md"; then
    nudges+=("📝 anti-patterns.md 变更 → 同步更新 tests/boundaries/ 检测")
fi

if [ ${#nudges[@]} -gt 0 ]; then
    echo ""
    echo "💡 文档同步提示（非阻断）："
    printf '  %s\n' "${nudges[@]}"
    echo ""
fi

exit 0  # 永远不阻断
