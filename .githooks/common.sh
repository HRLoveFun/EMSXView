#!/bin/bash
# common.sh — .githooks 共享函数库（被各 hook dot-source，勿直接执行）

# 依赖清单文件：内容变更时需重装对应依赖
DEPENDENCY_FILES=(
    "frontend/package-lock.json"
    "backend/api/requirements.txt"
    "CostView/requirements.txt"
    "MarketView/requirements.txt"
)

# 输出 hook 提示信息（统一前缀）
hook_info() {
    echo "[hook] $1"
}

# 检测两个提交之间依赖清单是否变更；命中则输出首个变更文件路径，否则输出空
# 用法: deps_changed_between <旧提交> <新提交>
deps_changed_between() {
    local old="$1" new="$2"
    git diff --name-only "$old" "$new" -- "${DEPENDENCY_FILES[@]}" 2>/dev/null | head -n 1
}

# 判断提交号是否为全零（新分支 / 新 worktree 初始态）
is_zero_sha() {
    case "$1" in
        00000000*) return 0 ;;
        *) return 1 ;;
    esac
}
