"""Normalize historical commit subjects to the standard `<type>: <subject>` form.

Used as a `git filter-branch --msg-filter` program: reads the commit message from
stdin and writes the (possibly rewritten) message to stdout. Unknown or
already-standard subjects pass through unchanged.
"""

import sys

MAPPING = {
    "baseline: verified working xsh source snapshot": "chore: baseline verified working xsh source snapshot",
    "iteration 1: startup readiness signal, continue-prompt fix, tests, restart supervisor": "feature: startup readiness signal, continue-prompt fix, tests, restart supervisor",
    "iteration 2: survive transient model errors in non-stop mode": "fix: survive transient model errors in non-stop mode",
    "iteration 3: resilient session loading": "fix: resilient session loading",
    "iteration 4: compaction tests (estimate, validation, manual compaction, pending guard)": "test: compaction coverage (estimate, validation, manual compaction, pending guard)",
    "iteration 5: AGENTS.md continuity protocol and README supervision docs": "docs: AGENTS.md continuity protocol and README supervision docs",
    "iteration 6: fix bounded() to never exceed limit; add config/prompt/tools tests": "fix: bounded() never exceeds the limit; add config/prompt/tools tests",
    "iteration 7: also retry connection/timeout at request establishment; model tests": "fix: retry connection/timeout at request establishment; model tests",
    "iteration 8: log request summaries instead of full bodies (fix O(n^2) session growth); add agent tests": "fix: log request summaries instead of full bodies (avoid O(n^2) session growth); agent tests",
    "iteration 9: stream session loading (lower peak memory on large sessions)": "perf: stream session loading to lower peak memory on large sessions",
    "iteration 10: file-tool tests (workspace confinement, read-before-write, edit semantics)": "test: file-tool coverage (workspace confinement, read-before-write, edit semantics)",
    "iteration 11: test automatic compaction trigger over threshold": "test: automatic compaction trigger over threshold",
    "iteration 13: shell-tool tests (execution, exit code, workspace cwd, timeout)": "test: shell-tool coverage (execution, exit code, workspace cwd, timeout)",
    "iteration 14: prompt-assembly tests": "test: prompt-assembly coverage",
    "iteration 15: report recovered interrupted tool calls on resume": "feature: report recovered interrupted tool calls on resume",
    "iteration 16: web-tool tests (url/ip validation, search parsing, html/markdown, formatting)": "test: web-tool coverage (url/ip validation, search parsing, html/markdown, formatting)",
    "iteration 17: pytest config (testpaths) and document optional env settings": "test: pytest config (testpaths) and document optional env settings",
    "iteration 18: compaction boundary tests (long single turn, insufficient history)": "test: compaction boundary cases (long single turn, insufficient history)",
    "iteration 19: handle SIGTERM via Ctrl+C shutdown path (clean repair on escalation)": "fix: handle SIGTERM via Ctrl+C shutdown path (clean repair on escalation)",
    "iteration 20: clean exit on Ctrl+C/SIGTERM during startup": "fix: clean exit on Ctrl+C/SIGTERM during startup",
    "iteration 21: tolerate isolated non-retryable turn errors in non-stop mode (bounded)": "fix: tolerate isolated non-retryable turn errors in non-stop mode (bounded)",
    "iteration 22: document supervisor self-test in AGENTS.md workflow": "docs: document supervisor self-test in AGENTS.md workflow",
    "iteration 23: include session progress (turns/messages) in readiness record": "feature: include session progress (turns/messages) in readiness record",
    "iteration 24: message/tool-call validation tests": "test: message/tool-call validation coverage",
    "iteration 25: compaction-checkpoint replay test": "test: compaction-checkpoint replay",
    "iteration 26: fix cli stage numbering consistency": "fix: cli stage numbering consistency",
    "iteration 27: complete README options table": "docs: complete README options table",
    "iteration 28: offline session-compaction utility (backup+validation) and opt-in supervisor step": "feature: offline session-compaction utility (backup+validation) and opt-in supervisor step",
    "iteration 29: add --version flag and stable prog name": "feature: add --version flag and stable prog name",
    "iteration 30: terminal rendering tests via injected console": "test: terminal rendering via injected console",
    "supervisor(iter31): snapshot before restart": "chore: supervisor snapshot before restart",
    "cleanup: remove user note after reading; drop its AGENTS.md line; ignore notes/swp": "chore: remove user note after reading; drop its AGENTS.md line; ignore notes/swp",
}

STANDARD_PREFIXES = ("feature: ", "fix: ", "docs: ", "test: ", "refactor: ", "chore: ", "perf: ", "style: ", "build: ", "ci: ")


def normalize(subject: str) -> str:
    if subject in MAPPING:
        return MAPPING[subject]
    if subject.startswith(STANDARD_PREFIXES):
        return subject
    return subject


def main() -> None:
    raw = sys.stdin.read()
    lines = raw.split("\n")
    lines[0] = normalize(lines[0])
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
