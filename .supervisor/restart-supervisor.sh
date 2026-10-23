#!/usr/bin/env bash
# restart-supervisor.sh — 独立于 xsh 进程运行的一次性重启/回滚监督脚本。
#
# 由外部 tmux session（xsh-supervisor）或其它可靠进程启动，负责：
#   1. 获取互斥锁，记录候选/已知良好提交、会话与日志位置
#   2. 提交本轮变更（失败候选保留为 git tag，便于诊断）
#   3. 通过 tmux 请求当前 xsh 正常退出，必要时只终止已核实的 xsh 进程
#   4. 确认 pane 回到 shell 后，通过发送按键执行恢复启动
#   5. 在限定时间内验证：就绪信号（关联本次启动）、进程存活、会话推进
#   6. 成功：把候选提交提升为已知良好；失败：回滚源码并再次启动已知良好版本
#
# 退出码：0=成功；10=失败后已回滚恢复；11=失败且无法恢复（已停止自动重试）；
#         2=配置/前置条件错误；75=已有其它监督进程持锁。
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${XSH_PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
STATE_DIR="${XSH_SUPERVISOR_STATE:-$SCRIPT_DIR}"
LOG_DIR="$STATE_DIR/logs"
READY_FILE="$STATE_DIR/ready.json"
LOCK_FILE="$STATE_DIR/lock"
STATE_FILE="$STATE_DIR/state.json"
TARGET_SESSION="${XSH_TARGET_SESSION:-xsh}"
LABEL="${XSH_RESTART_LABEL:-manual}"

STOP_TIMEOUT="${XSH_STOP_TIMEOUT:-25}"
STOP_DELAY="${XSH_STOP_DELAY:-3}"
READY_TIMEOUT="${XSH_READY_TIMEOUT:-150}"
HEALTH_WAIT="${XSH_HEALTH_WAIT:-15}"

mkdir -p "$LOG_DIR"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

SESSION_FILE="${XSH_SESSION_FILE:-}"

# 严格验证：等待就绪文件出现，并确认进程存活且会话推进。
# 参数：$1 本次启动时刻(epoch float) $2 启动前的会话大小
strict_verify() {
    local launch_epoch="$1" before_size="$2" ready=0 deadline now new_size advanced=0
    deadline=$(( $(date +%s) + READY_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if ready_ok "$launch_epoch" "$PANE_PID"; then ready=1; break; fi
        now=$(date +%s)
        if [ -z "$(xsh_pids_under "$PANE_PID")" ] && ! pane_is_python "$TARGET_PANE" \
           && [ "$now" -gt $(( ${launch_epoch%.*} + 5 )) ]; then
            log "startup process exited before readiness appeared"
            return 1
        fi
        sleep 1
    done
    [ "$ready" = 1 ] || { log "readiness not observed within ${READY_TIMEOUT}s"; return 1; }
    log "readiness observed: $(jget "$READY_FILE" boot_id 2>/dev/null || echo '?')"
    sleep "$HEALTH_WAIT"
    ready_ok "$launch_epoch" "$PANE_PID" || { log "process did not stay alive after health wait"; return 1; }
    count="$(xsh_pids_under "$PANE_PID" | grep -c .)"
    if [ "$count" != "1" ]; then
        log "expected exactly one xsh process under pane, found ${count}"
        return 1
    fi
    if [ -x "$PROJECT_DIR/.venv/bin/xsh" ]; then
        if (cd "$PROJECT_DIR" && .venv/bin/xsh --doctor >/dev/null 2>&1); then
            log "doctor check passed"
        else
            log "doctor check reported issues (non-fatal; run xsh --doctor to inspect)"
        fi
    fi
    new_size="$(file_size "${SESSION_FILE:-/nonexistent}")"
    session_advanced "$before_size" && advanced=1
    if [ "$advanced" = 1 ]; then
        log "health check passed (pid $(jget "$READY_FILE" pid), session ${before_size} -> ${new_size})"
        return 0
    fi
    log "process alive but session did not advance (${before_size} -> ${new_size})"
    return 1
}

# 降级验证：目标提交不支持就绪文件时使用。
# 要求：pane 下存在存活的 xsh 进程、前台仍是 python、会话在启动后推进。
fallback_verify() {
    local launch_epoch="$1" before_size="$2" deadline new_size advanced=0
    deadline=$(( $(date +%s) + READY_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ -n "$(xsh_pids_under "$PANE_PID")" ] && pane_is_python "$TARGET_PANE"; then
            break
        fi
        sleep 1
    done
    [ -n "$(xsh_pids_under "$PANE_PID")" ] || { log "fallback: no live xsh process"; return 1; }
    sleep "$HEALTH_WAIT"
    [ -n "$(xsh_pids_under "$PANE_PID")" ] || { log "fallback: process exited during health wait"; return 1; }
    count="$(xsh_pids_under "$PANE_PID" | grep -c .)"
    [ "$count" = "1" ] || { log "fallback: expected one xsh process, found ${count}"; return 1; }
    new_size="$(file_size "${SESSION_FILE:-/nonexistent}")"
    session_advanced "$before_size" || { log "fallback: session did not advance"; return 1; }
    log "fallback verification passed"
    return 0
}

verify_launch() {
    if supports_ready_file; then
        strict_verify "$1" "$2"
    else
        log "target commit lacks --ready-file; using fallback verification"
        fallback_verify "$1" "$2"
    fi
}

# ============================================================
# 主流程
# ============================================================
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another supervisor run holds the lock; exiting"
    exit 75
fi
log "=== restart-supervisor start label=$LABEL project=$PROJECT_DIR ==="

git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { log "FATAL: $PROJECT_DIR is not a git worktree"; exit 2; }

# 步骤 2：提交本轮变更，保留候选版本
git -C "$PROJECT_DIR" add -A -- . >/dev/null 2>&1 || true
if ! git -C "$PROJECT_DIR" diff --cached --quiet 2>/dev/null; then
    git -C "$PROJECT_DIR" commit -q -m "supervisor($LABEL): snapshot before restart" >/dev/null 2>&1 || true
fi
candidate="$(git -C "$PROJECT_DIR" rev-parse HEAD)"

good="${XSH_GOOD_COMMIT:-$(jget "$STATE_FILE" good_commit || true)}"
if [ -z "$good" ]; then
    log "FATAL: no known-good commit recorded in $STATE_FILE; refusing to restart"
    exit 2
fi
git -C "$PROJECT_DIR" cat-file -e "${good}^{commit}" >/dev/null 2>&1 || { log "FATAL: known-good commit $good not found"; exit 2; }
# 校验已知良好提交对象存在。
candidate="$(git -C "$PROJECT_DIR" rev-parse "$candidate")"
good="$(git -C "$PROJECT_DIR" rev-parse "$good")"

ts="$(date -u +%Y%m%d-%H%M%S)"
tag="restart-candidate-$ts"
git -C "$PROJECT_DIR" tag -f "$tag" "$candidate" >/dev/null 2>&1 || true
save_state label="$LABEL" candidate_commit="$candidate" candidate_tag="$tag" good_commit="$good" \
    target_session="$TARGET_SESSION" updated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "candidate=$candidate good=$good candidate_tag=$tag"

# 步骤 1/3：定位目标 pane 与当前 xsh 会话
find_target_pane || { log "FATAL: no pane found in tmux session '$TARGET_SESSION'"; exit 2; }
save_state target_pane="$TARGET_PANE" pane_pid="$PANE_PID"
log "target pane=$TARGET_PANE pane_pid=$PANE_PID command=$(pane_command "$TARGET_PANE")"

if [ -z "$SESSION_FILE" ]; then
    SESSION_FILE="$(latest_session)"
fi
session_size="$(file_size "${SESSION_FILE:-/nonexistent}")"
save_state session="${SESSION_FILE:-}" session_size_before="$session_size"
log "session=${SESSION_FILE:-<none>} size_before=$session_size"

# 步骤 3：请求当前 xsh 正常退出
# 先留出短暂缓冲，让触发本次重启的调用来得及返回（监督脚本本身在 tmux 中不受影响）。
[ "$STOP_DELAY" -gt 0 ] && { log "waiting ${STOP_DELAY}s before stopping"; sleep "$STOP_DELAY"; }
old_pids="$(xsh_pids_under "$PANE_PID" | tr '\n' ' ')"
if [ -n "${old_pids// /}" ]; then
    log "stopping existing xsh pids: $old_pids"
    tmux send-keys -t "$TARGET_PANE" C-c
    if ! wait_xsh_gone "$STOP_TIMEOUT"; then
        log "still alive after C-c; sending second interrupt"
        tmux send-keys -t "$TARGET_PANE" C-c
        if ! wait_xsh_gone 8; then
            kill_xsh_under TERM
            if ! wait_xsh_gone 8; then
                kill_xsh_under KILL
                wait_xsh_gone 5 || log "WARN: xsh still alive after SIGKILL"
            fi
        fi
    fi
    log "old xsh stopped"
else
    log "no xsh process currently running under pane $TARGET_PANE"
fi

# 确认 pane 已返回 shell（前台不再是 python）
for _ in $(seq 1 20); do
    ! pane_is_python "$TARGET_PANE" && break
    sleep 0.5
done
save_state current_command_after_stop="$(pane_command "$TARGET_PANE")" 

# 可选：在 xsh 停止期间离线压缩超大的会话文件（保留 .bak，校验失败则不替换）。
# 触发条件：显式 XSH_COMPACT_SESSION=1，或会话文件超过 XSH_COMPACT_THRESHOLD_MB（默认 20MB）。
# 失败只记录、不影响重启。
compact_session=0
[ "${XSH_COMPACT_SESSION:-0}" = "1" ] && compact_session=1
if [ -n "$SESSION_FILE" ] && [ -f "$SESSION_FILE" ]; then
    threshold_bytes=$(( ${XSH_COMPACT_THRESHOLD_MB:-20} * 1024 * 1024 ))
    if [ "$(file_size "$SESSION_FILE")" -gt "$threshold_bytes" ]; then compact_session=1; fi
fi
if [ "$compact_session" = 1 ] && [ -n "$SESSION_FILE" ] && [ -f "$SESSION_FILE" ]; then
    log "compacting session file offline (size $(file_size "$SESSION_FILE") bytes)"
    if (cd "$PROJECT_DIR" && .venv/bin/python -m xsh.maintenance "$SESSION_FILE") >>"$LOG_DIR/session-compaction.log" 2>&1; then
        session_size="$(file_size "$SESSION_FILE")"
        log "session compaction step done; size now $session_size"
    else
        log "WARN: session compaction failed; continuing with original"
    fi
fi

# 步骤 4/5：启动候选版本并验证
launch_epoch="$(send_launch)"
if ! is_epoch "$launch_epoch"; then
    log "FATAL: invalid launch epoch captured (got '$launch_epoch'); aborting before any stop/rollback"
    exit 2
fi
if verify_launch "$launch_epoch" "$session_size"; then
    new_pid="$(jget "$READY_FILE" pid 2>/dev/null || echo '')"
    running="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo '?')"
    [ "$running" = "$candidate" ] || log "WARN: running source HEAD=$running differs from candidate=$candidate"
    git -C "$PROJECT_DIR" tag -f "known-good-latest" "$candidate" >/dev/null 2>&1 || true
    save_state good_commit="$candidate" good_tag="known-good-latest" last_status="ok" \
        last_restart_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" last_pid="$new_pid" running_commit="$running" recovered=0
    capture_pane_log "pane-after-success.log"
    log "RESTART OK: $candidate promoted to known good (pid ${new_pid:-?}, HEAD=$running)"
    exit 0
fi

# 步骤 7：失败处理——保存日志、清理失败实例、回滚源码、写 RESTART_FAILED.json
log "RESTART FAILED: candidate $candidate did not become healthy"
capture_pane_log "pane-after-failure.log"
kill_xsh_under TERM
if ! wait_xsh_gone 8; then
    kill_xsh_under KILL
    wait_xsh_gone 5 || true
fi

if [ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
    stash_msg="supervisor-rollback-$ts"
    git -C "$PROJECT_DIR" stash push -u -m "$stash_msg" >/dev/null 2>&1 && save_state rollback_stash="$stash_msg" || true
fi
if ! git -C "$PROJECT_DIR" reset --hard "$good" >/dev/null 2>&1; then
    log "WARN: git reset --hard $good failed"
fi
git -C "$PROJECT_DIR" clean -fd >/dev/null 2>&1 || true
log "rolled back working tree to $good"

python3 - "$PROJECT_DIR/RESTART_FAILED.json" "$candidate" "$good" "$tag" "$LOG_DIR" "$LABEL" <<'PY'
import json, sys
from datetime import datetime, timezone
path, failed, recovered, tag, logdir, label = sys.argv[1:7]
data = {
    "failed_commit": failed,
    "failed_candidate_tag": tag,
    "recovered_commit": recovered,
    "label": label,
    "time": datetime.now(timezone.utc).isoformat(),
    "summary": "Candidate build did not reach a healthy resumed session within the timeout.",
    "log_dir": logdir,
    "pane_log": f"{logdir}/pane-after-failure.log",
    "supervisor_log": f"{logdir}/supervisor.log",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
PY
log "wrote RESTART_FAILED.json (failed=$candidate, recovered=$good)"

# 步骤 8/9：再次启动已知良好版本并验证
launch_epoch="$(send_launch)"
if ! is_epoch "$launch_epoch"; then
    log "FATAL: invalid recovery launch epoch (got '$launch_epoch')"
    save_state last_status="blocked" recovered=0
    touch "$STATE_DIR/no-auto-restart"
    exit 11
fi
if verify_launch "$launch_epoch" "$session_size"; then
    save_state good_commit="$good" last_status="rollback_recovered" recovered=1 \
        last_restart_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    capture_pane_log "pane-after-recovery.log"
    log "RECOVERED: known-good $good is running again"
    exit 10
fi

save_state last_status="blocked" recovered=0
touch "$STATE_DIR/no-auto-restart"
capture_pane_log "pane-after-blocked.log"
log "BLOCKED: could not recover known-good $good; stopping automatic retries"
exit 11
