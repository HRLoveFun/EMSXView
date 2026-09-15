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

# 判断工作树是否有未提交改动（含 staged 与 unstaged）
is_worktree_dirty() {
    [ -n "$(git status --porcelain)" ]
}

# 判断是否处于 rebase / merge 中间态（此时禁止叠加任何自动 rebase）
is_sequencing_in_progress() {
    [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
        [ -d "$(git rev-parse --git-path rebase-apply)" ] ||
        [ -f "$(git rev-parse --git-path MERGE_HEAD)" ]
}

# ═══════════════════════════════════════════════════════════════════════
# 会话独占锁（防止同一工作目录被多个 IDE / Agent 会话并发写 index）
#
# 锁文件按工作树隔离：主工作树 .git/EMSXVIEW_SESSION_LOCK；
# 链接工作树 .git/worktrees/<name>/EMSXVIEW_SESSION_LOCK
# （由 git rev-parse --absolute-git-dir 保证，见 lock_file）。
# 因此「各任务各自建 worktree」的规范用法天然互不抢锁；
# 只有两个会话落在同一个工作目录时才会碰撞 —— 正是要拦截的场景。
#
# 开关 / 调参：
#   EMSXVIEW_SESSION_ID     显式声明会话标识（优先于自动探测）
#   EMSXVIEW_LOCK_TTL       静默超过该秒数视为陈旧锁，可被自动接管（默认 1800）
#   EMSXVIEW_LOCK_TAKEOVER  =true 时强制接管（确认对方已收工）
#
# 机制说明见 docs/spec/git-workflow.md §10。
# ═══════════════════════════════════════════════════════════════════════

# 锁文件绝对路径（按工作树隔离）
lock_file() {
    printf '%s/EMSXVIEW_SESSION_LOCK' "$(git rev-parse --absolute-git-dir 2>/dev/null)"
}

# 当前会话标识；无法确定时返回非零（调用方降级为仅提示，不阻断）
lock_session_id() {
    if [ -n "$EMSXVIEW_SESSION_ID" ]; then printf 'x-%s' "$EMSXVIEW_SESSION_ID"; return 0; fi
    if [ -n "$CODEBUDDY_SESSION_ID" ]; then printf 'cb-%s' "$CODEBUDDY_SESSION_ID"; return 0; fi
    if [ -n "$CLAUDE_SESSION_ID" ]; then printf 'cc-%s' "$CLAUDE_SESSION_ID"; return 0; fi
    if [ -n "$TERM_SESSION_ID" ]; then printf 'term-%s' "$TERM_SESSION_ID"; return 0; fi
    if [ -n "$WT_SESSION" ]; then printf 'wt-%s' "$WT_SESSION"; return 0; fi
    if [ -n "$VSCODE_PID" ]; then printf 'vscode-%s' "$VSCODE_PID"; return 0; fi
    return 1
}

# 读取锁文件字段；文件不存在或字段缺失时输出空
lock_field() {
    [ -f "$1" ] || return 0
    sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1
}

# 锁静默时长（秒）；无 heartbeat 记录时返回非零
lock_idle_seconds() {
    local hb
    hb="$(lock_field "$1" heartbeat)"
    [ -n "$hb" ] || return 1
    printf '%s' "$(( $(date +%s) - hb ))"
}

# 写入 / 刷新锁（保留首次 acquired 时间）
lock_write() {
    local lf="$1" sid="$2" acq
    acq="$(lock_field "$lf" acquired)"
    [ -n "$acq" ] || acq="$(date +%s)"
    {
        printf 'session=%s\n'   "$sid"
        printf 'host=%s\n'      "${COMPUTERNAME:-$(hostname 2>/dev/null)}"
        printf 'worktree=%s\n'  "$(git rev-parse --show-toplevel 2>/dev/null)"
        printf 'branch=%s\n'    "$(git branch --show-current 2>/dev/null)"
        printf 'owner=%s\n'     "$(git config user.email 2>/dev/null)"
        printf 'acquired=%s\n'  "$acq"
        printf 'heartbeat=%s\n' "$(date +%s)"
    } > "$lf" 2>/dev/null || true
}

# 打印锁冲突的处置指引
lock_report_conflict() {
    local lf="$1" sid="$2" idle="$3"
    hook_info "已阻断：本工作目录已被另一个会话占用"
    hook_info "  持有 session : $(lock_field "$lf" session)"
    hook_info "  本会话 session: $sid"
    hook_info "  持有 host    : $(lock_field "$lf" host)"
    hook_info "  持有 branch  : $(lock_field "$lf" branch)"
    hook_info "  静默时长     : ${idle}s（TTL ${EMSXVIEW_LOCK_TTL:-1800}s 后自动接管）"
    hook_info "处置（见 docs/spec/git-workflow.md §10）:"
    hook_info "  1) 规范做法：为当前任务另建 worktree —— scripts/devtools/wt-new.ps1 <task>"
    hook_info "  2) 确认对方已收工：EMSXVIEW_LOCK_TAKEOVER=true git commit ..."
    hook_info "  3) 查看各目录锁状态：scripts/devtools/wt-list.ps1"
}

# 校验 / 获取本工作目录独占锁；0 = 放行，1 = 阻断
lock_verify() {
    local lf sid holder idle ttl
    lf="$(lock_file)"
    [ -n "$lf" ] || return 0

    sid="$(lock_session_id)" || {
        hook_info "未检测到会话标识（EMSXVIEW_SESSION_ID / CODEBUDDY_SESSION_ID / VSCODE_PID 均未设置），独占锁保护未生效"
        return 0
    }
    ttl="${EMSXVIEW_LOCK_TTL:-1800}"

    if [ "$EMSXVIEW_LOCK_TAKEOVER" = "true" ]; then
        lock_write "$lf" "$sid"
        hook_info "已按 EMSXVIEW_LOCK_TAKEOVER=true 接管本工作目录独占锁（session=$sid）"
        return 0
    fi

    holder="$(lock_field "$lf" session)"
    if [ -z "$holder" ] || [ "$holder" = "$sid" ]; then
        lock_write "$lf" "$sid"
        return 0
    fi

    idle="$(lock_idle_seconds "$lf")" || idle=""
    if [ -n "$idle" ] && [ "$idle" -ge "$ttl" ]; then
        hook_info "检测到陈旧独占锁（持有者 $holder 静默 ${idle}s ≥ TTL ${ttl}s），已自动接管"
        lock_write "$lf" "$sid"
        return 0
    fi

    lock_report_conflict "$lf" "$sid" "${idle:-未知}"
    return 1
}
