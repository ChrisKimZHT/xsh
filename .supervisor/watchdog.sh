#!/usr/bin/env bash
# watchdog.sh — 常驻看护脚本，作为重启失败后的最终保底。
#
# 运行在独立的 tmux session（xsh-watchdog）中，独立于 xsh 与一次性
# restart-supervisor.sh。它周期性检查目标 pane：
#   - 有存活的 xsh 进程：正常，重置计时。
#   - 没有 xsh 进程且互斥锁被监督脚本持有：正在重启，跳过一次。
#   - 没有 xsh 进程且持续超过 GRACE 秒：判定为意外退出，重新启动当前源码。
# 连续恢复失败达到 FAIL_LIMIT 次时写入 no-auto-restart 标记并退出，
# 停止无意义的重启（符合“不得无限重启”的要求）。
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${XSH_PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
STATE_DIR="${XSH_SUPERVISOR_STATE:-$SCRIPT_DIR}"
LOG_DIR="$STATE_DIR/logs"
STATE_FILE="$STATE_DIR/state.json"
READY_FILE="$STATE_DIR/ready.json"
LOCK_FILE="$STATE_DIR/lock"
TARGET_SESSION="${XSH_TARGET_SESSION:-xsh}"
NO_AUTO="$STATE_DIR/no-auto-restart"

INTERVAL="${XSH_WATCHDOG_INTERVAL:-15}"
GRACE="${XSH_WATCHDOG_GRACE:-45}"
FAIL_LIMIT="${XSH_WATCHDOG_FAIL_LIMIT:-3}"
HEALTH_WAIT="${XSH_WATCHDOG_HEALTH_WAIT:-12}"
READY_TIMEOUT_WD="${XSH_WATCHDOG_READY_TIMEOUT:-120}"

SESSION_FILE=""
mkdir -p "$LOG_DIR"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

log "watchdog started (interval=${INTERVAL}s grace=${GRACE}s fail_limit=${FAIL_LIMIT})"

if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
    log "watchdog: target session '$TARGET_SESSION' not present at start; continuing anyway"
fi

absence=0
failures=0

while true; do
    if [ -f "$NO_AUTO" ]; then
        log "watchdog: no-auto-restart flag present; exiting"
        exit 0
    fi

    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null || ! find_target_pane; then
        sleep "$INTERVAL"
        continue
    fi

    if [ -n "$(xsh_pids_under "$PANE_PID")" ]; then
        absence=0
        sleep "$INTERVAL"
        continue
    fi

    # 互斥锁被持有说明一次性监督脚本正在重启，交给它处理。
    if ! flock -n "$LOCK_FILE" -c true 2>/dev/null; then
        absence=0
        sleep "$INTERVAL"
        continue
    fi

    absence=$((absence + INTERVAL))
    if [ "$absence" -lt "$GRACE" ]; then
        log "watchdog: no xsh for ${absence}s (grace ${GRACE}s)"
        sleep "$INTERVAL"
        continue
    fi

    log "watchdog: xsh absent for ${absence}s; relaunching current source"
    SESSION_FILE="$(latest_session)"
    before="$(file_size "${SESSION_FILE:-/nonexistent}")"
    launch_epoch="$(send_launch)"
    if ! is_epoch "$launch_epoch"; then
        log "watchdog: invalid launch epoch '$launch_epoch'; skipping this attempt"
        sleep "$INTERVAL"
        continue
    fi

    recovered=0
    deadline=$(( $(date +%s) + READY_TIMEOUT_WD ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if supports_ready_file; then
            ready_ok "$launch_epoch" "$PANE_PID" && { recovered=1; break; }
        else
            [ -n "$(xsh_pids_under "$PANE_PID")" ] && pane_is_python "$TARGET_PANE" && { recovered=1; break; }
        fi
        sleep 1
    done
    if [ "$recovered" = 1 ]; then
        sleep "$HEALTH_WAIT"
        if session_advanced "$before" && [ -n "$(xsh_pids_under "$PANE_PID")" ]; then
            log "watchdog: relaunch verified"
            absence=0
            failures=0
            save_state last_status="watchdog_recovered" last_restart_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            sleep "$INTERVAL"
            continue
        fi
    fi

    failures=$((failures + 1))
    log "watchdog: relaunch attempt $failures failed"
    capture_pane_log "watchdog-failure-$failures.log"
    if [ "$failures" -ge "$FAIL_LIMIT" ]; then
        touch "$NO_AUTO"
        save_state last_status="watchdog_blocked" recovered=0 failures="$failures"
        log "watchdog: $FAIL_LIMIT consecutive failures; writing $NO_AUTO and stopping"
        exit 2
    fi
    # 清理失败的实例，等待下一轮
    kill_xsh_under TERM
    wait_xsh_gone 5 || kill_xsh_under KILL
    absence=0
    sleep "$INTERVAL"
done
