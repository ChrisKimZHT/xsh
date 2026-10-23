#!/usr/bin/env bash
# selftest.sh — 监督脚本纯函数的离线自检（不接触真实 xsh / tmux）。
# 运行：bash /root/xsh-non-stop-mode/.supervisor/selftest.sh
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT_DIR="${XSH_PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
export STATE_DIR="$SCRIPT_DIR"
export LOG_DIR="$SCRIPT_DIR/logs"
export TARGET_SESSION="${XSH_TARGET_SESSION:-xsh}"
export READY_FILE="$SCRIPT_DIR/selftest-ready.json"
export STATE_FILE="$SCRIPT_DIR/state.json"

# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

failures=0
check() {  # check <name> <bash-condition>
    if eval "$2"; then
        printf 'PASS %s\n' "$1"
    else
        printf 'FAIL %s\n' "$1"
        failures=$((failures + 1))
    fi
}

check "is_epoch accepts float" 'is_epoch 1792740179.9051783'
check "is_epoch accepts int" 'is_epoch 1792740179'
check "is_epoch rejects log text" '! is_epoch "2026-10-23T07:22:59Z [pid 1] launch command: cd"'
check "is_epoch rejects empty" '! is_epoch ""'

check "supports_ready_file true" 'supports_ready_file'

SESSION_FILE=""
out="$(build_launch_cmd)"
check "launch without session uses resume" 'case "$out" in *"--resume --allow-shell"*) true;; *) false;; esac'

SESSION_FILE="/tmp/example-session.jsonl"
out="$(build_launch_cmd)"
check "session path follows --resume" 'case "$out" in *"--resume /tmp/example-session.jsonl"*) true;; *) false;; esac'
check "launch includes ready-file" 'case "$out" in *"--ready-file"*) true;; *) false;; esac'
check "launch cds to project" 'case "$out" in "cd -- $PROJECT_DIR "*) true;; *) false;; esac'

python3 - "$READY_FILE" "$$" <<'PY'
import json, sys, time
json.dump({"epoch": time.time(), "pid": int(sys.argv[2]), "ppid": 999}, open(sys.argv[1], "w"))
PY
check "ready_ok accepts fresh live record" 'ready_ok 0 999'
check "ready_ok rejects stale record" '! ready_ok 9999999999 999'
check "ready_ok rejects wrong parent" '! ready_ok 0 123456'
rm -f "$READY_FILE"

check "is_xsh_pid rejects bash" '! is_xsh_pid $$'

# pane_is_python 需要 tmux；仅在目标 pane 存在时检查。
if find_target_pane; then
    cmd="$(pane_command "$TARGET_PANE")"
    printf 'INFO target pane=%s pid=%s cmd=%s\n' "$TARGET_PANE" "$PANE_PID" "$cmd"
    check "find_target_pane picks an xsh pane" '[ -n "$(xsh_pids_under "$PANE_PID")" ]'
fi

echo "---"
if [ "$failures" -eq 0 ]; then
    echo "selftest: ALL PASS"
    exit 0
fi
echo "selftest: $failures FAILURE(S)"
exit 1
