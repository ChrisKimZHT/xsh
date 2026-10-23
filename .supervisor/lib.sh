#!/usr/bin/env bash
# lib.sh — 重启监督脚本共享函数。
#
# 该目录（.supervisor/）被 .gitignore 忽略，因此源码回滚（git reset --hard /
# git clean -fd，均不带 -x）不会破坏监督脚本、日志与状态。
# 约定环境变量：
#   PROJECT_DIR    目标仓库根目录
#   TARGET_SESSION 用户观察 xsh 的 tmux session 名
#   STATE_DIR      监督脚本状态、日志、就绪文件所在目录

# 日志输出到 stderr（避免污染 $(...) 命令替换捕获的 stdout），同时追加到日志文件。
log() {
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) [pid $$] $*"
    printf '%s\n' "$line" >&2
    if [ -n "${LOG_DIR:-}" ] && [ -d "$LOG_DIR" ]; then
        printf '%s\n' "$line" >>"$LOG_DIR/supervisor.log"
    fi
    return 0
}

# 从 JSON 文件读取一个键；不存在时返回非零。
jget() {
    python3 - "$1" "$2" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
value = data.get(sys.argv[2])
if value is None:
    sys.exit(1)
print(value)
PY
}

# 原子地写入/更新状态文件：save_state key=value [key=value ...]
save_state() {
    python3 - "$STATE_FILE" "$@" <<'PY'
import json, os, sys
path = sys.argv[1]
updates = dict(arg.split("=", 1) for arg in sys.argv[2:])
try:
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, dict):
        data = {}
except Exception:
    data = {}
data.update(updates)
tmp = f"{path}.tmp.{os.getpid()}"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
os.replace(tmp, path)
PY
}

# 递归列出某个进程的全部后代 PID。
descendants() {
    local root="$1" pid child
    local -a stack=("$root")
    while [ "${#stack[@]}" -gt 0 ]; do
        pid="${stack[0]}"
        stack=("${stack[@]:1}")
        while IFS= read -r child; do
            [ -n "$child" ] || continue
            printf '%s\n' "$child"
            stack+=("$child")
        done < <(pgrep -P "$pid" 2>/dev/null || true)
    done
    return 0
}

# 判断 PID 是否为本项目的 xsh 进程。
# 依据：可执行文件是 Python 解释器，且 argv[1] 是 xsh 控制台脚本（以 /xsh 结尾）。
# 这样既能识别本项目的 xsh，又不会误伤由 shell 工具启动、命令行里恰好含 "xsh"
# 的 bash 包装进程。注意：xsh 进程的 comm 可能是 "xsh" 而非 "python"。
is_xsh_pid() {
    local pid="$1" exe script
    exe="$(readlink "/proc/$pid/exe" 2>/dev/null || true)"
    case "$exe" in
        *python*) ;;
        *) return 1 ;;
    esac
    script="$(tr '\0' '\n' <"/proc/$pid/cmdline" 2>/dev/null | sed -n '2p')"
    case "$script" in
        */xsh | xsh) return 0 ;;
        *) return 1 ;;
    esac
}

# 列出目标 pane 下的全部 xsh 进程 PID。
xsh_pids_under() {
    local root="$1" pid
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        is_xsh_pid "$pid" && printf '%s\n' "$pid"
    done < <(descendants "$root")
    return 0
}

# 定位目标 pane：
#   1) 优先选择当前确实运行着 xsh 进程的 pane（最可靠）
#   2) 其次选择工作目录等于 PROJECT_DIR 的 pane
#   3) 最后退回到该 session 的第一个 pane
find_target_pane() {
    local pane path pid live_pane="" live_pid="" path_pane="" path_pid="" any_pane="" any_pid=""
    while IFS='|' read -r pane path pid; do
        [ -n "$pane" ] || continue
        if [ -z "$any_pane" ]; then any_pane="$pane"; any_pid="$pid"; fi
        if [ -z "$live_pane" ] && [ -n "$(xsh_pids_under "$pid")" ]; then
            live_pane="$pane"; live_pid="$pid"
        fi
        if [ -z "$path_pane" ] && [ "$path" = "$PROJECT_DIR" ]; then
            path_pane="$pane"; path_pid="$pid"
        fi
    done < <(tmux list-panes -s -t "$TARGET_SESSION" -F '#{pane_id}|#{pane_current_path}|#{pane_pid}' 2>/dev/null || true)
    if [ -n "$live_pane" ]; then TARGET_PANE="$live_pane"; PANE_PID="$live_pid"; return 0; fi
    if [ -n "$path_pane" ]; then TARGET_PANE="$path_pane"; PANE_PID="$path_pid"; return 0; fi
    [ -n "$any_pane" ] || return 1
    TARGET_PANE="$any_pane"
    PANE_PID="$any_pid"
    return 0
}

# pane 当前前台命令。
pane_command() {
    tmux display-message -p -t "$1" '#{pane_current_command}' 2>/dev/null || true
}

# pane 前台是否为 Python 进程（xsh 正在运行）。
pane_is_python() {
    case "$(pane_command "$1")" in
        python | python3 | python3.*) return 0 ;;
        *) return 1 ;;
    esac
}

# 就绪文件是否属于本次启动：
#   1) 文件存在且可解析，epoch 晚于本次启动时刻
#   2) 记录的 PID 仍然存活
#   3) 记录的 ppid 等于 pane 的 shell PID（即由目标 pane 启动）
ready_ok() {
    local min_epoch="$1" pane_pid="$2"
    [ -f "$READY_FILE" ] || return 1
    python3 - "$READY_FILE" "$min_epoch" "$pane_pid" <<'PY'
import json, os, sys
path, min_epoch, pane_pid = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    sys.exit(1)
if float(data.get("epoch", 0)) < min_epoch:
    sys.exit(1)
pid = data.get("pid")
if not isinstance(pid, int) or pid <= 0:
    sys.exit(1)
try:
    os.kill(pid, 0)
except OSError:
    sys.exit(1)
if isinstance(data.get("ppid"), int) and data["ppid"] == pane_pid:
    sys.exit(0)
# 退回到“是 pane shell 的后代”判断，兼容中间包装进程。
seen, current = set(), pid
while current and current not in seen and current != 1:
    seen.add(current)
    if current == pane_pid:
        sys.exit(0)
    try:
        stat = open(f"/proc/{current}/stat", encoding="utf-8").read()
        current = int(stat[stat.rfind(")") + 2:].split()[1])
    except Exception:
        sys.exit(1)
sys.exit(1)
PY
}

# 构造要在目标 pane 中执行的恢复启动命令。
# 注意：--resume 的路径参数必须紧跟其后，否则会被当成位置参数 prompt。
build_launch_cmd() {
    local flags="--resume"
    if [ -n "${SESSION_FILE:-}" ]; then
        flags="$flags $(printf '%q' "$SESSION_FILE")"
    fi
    flags="$flags --allow-shell"
    if supports_ready_file; then
        flags="$flags --ready-file $(printf '%q' "$READY_FILE")"
    fi
    printf 'cd -- %q && .venv/bin/xsh %s' "$PROJECT_DIR" "$flags"
}

# 把目标 pane 的内容追加保存到日志。
capture_pane_log() {
    local name="$1"
    tmux capture-pane -p -S -400 -t "$TARGET_PANE" 2>/dev/null >>"$LOG_DIR/$name" || true
}

# 等待目标 pane 下的 xsh 进程全部退出。
wait_xsh_gone() {
    local timeout="$1" deadline
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ -z "$(xsh_pids_under "$PANE_PID")" ]; then return 0; fi
        sleep 0.5
    done
    [ -z "$(xsh_pids_under "$PANE_PID")" ]
}

# 终止已核实的 xsh 进程（仅限本项目、目标 pane 下的解释器进程）。
kill_xsh_under() {
    local signal="$1" pid
    for pid in $(xsh_pids_under "$PANE_PID"); do
        log "sending SIG$signal to verified xsh pid $pid"
        kill "-$signal" "$pid" 2>/dev/null || true
    done
    return 0
}

# 最近修改的会话文件。
latest_session() {
    ls -1t "$PROJECT_DIR/.xsh/sessions"/*.jsonl 2>/dev/null | head -n 1
}

# 文件大小（字节），失败返回 0。
file_size() {
    stat -c %s "$1" 2>/dev/null || echo 0
}

# 当前源码是否支持就绪文件机制。
supports_ready_file() {
    grep -q -- '--ready-file' "$PROJECT_DIR/src/xsh/cli.py" 2>/dev/null
}

# 向目标 pane 发送恢复启动命令，返回本次启动时刻（epoch float）。
# 依赖 TARGET_PANE、READY_FILE、SESSION_FILE（可选）与 build_launch_cmd。
# 注意：函数 stdout 必须只包含 epoch，调用方用 $(...) 捕获；日志一律走 stderr。
send_launch() {
    local cmd launch_epoch
    rm -f "$READY_FILE"
    launch_epoch="$(
        python3 - <<'PY'
import time
print(f"{time.time():.6f}")
PY
    )"
    cmd="$(build_launch_cmd)"
    log "launch command: $cmd"
    tmux send-keys -t "$TARGET_PANE" -l "$cmd"
    tmux send-keys -t "$TARGET_PANE" Enter
    printf '%s' "$launch_epoch"
}

# 校验 epoch 字符串是否为有效数字，防止命令替换捕获到多余输出。
is_epoch() {
    case "$1" in
        '' | *[!0-9.]*) return 1 ;;
        *.*) return 0 ;;
        *) return 0 ;;
    esac
}

# 会话是否在启动后推进，用于验证“恢复成功”。
session_advanced() {
    local before_size="$1" after_size
    after_size="$(file_size "${SESSION_FILE:-/nonexistent}")"
    if [ -n "${SESSION_FILE:-}" ]; then
        [ "$after_size" -gt "$before_size" ]
    else
        [ "$after_size" -gt 0 ]
    fi
}

