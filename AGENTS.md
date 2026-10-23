# AGENTS.md — 本仓库的自迭代约定

本文件会被 xsh 作为项目指令自动加入系统提示词，因此**每次恢复运行都会生效**。

## 环境事实（已核实）

- 仓库根 / 工作目录：`/root/xsh-non-stop-mode`；入口：`.venv/bin/xsh`。
- 用户观察用 tmux session：`xsh`；运行中的 xsh 位于其中运行着 xsh 进程的 pane
  （会话内可能还有其它窗口，`tmux list-panes` 需加 `-s` 才能列出会话内全部 pane）。
- 会话文件：`.xsh/sessions/*.jsonl`；`xsh --resume <path>` 恢复指定会话，
  省略 path 时恢复最近修改的会话。
- 监督脚本与记录目录：`.supervisor/`（gitignored，回滚不会破坏）：
  - `PROGRESS.md`：迭代记录、改进清单、经验教训（**恢复后先读它**）。
  - `state.json`：已知良好提交、候选提交、上次重启状态。
  - `logs/supervisor.log`：监督脚本日志。
  - `restart-supervisor.sh` / `watchdog.sh`：重启监督与保底看护。
- `RESTART_FAILED.json`（仓库根，gitignored，仅失败时出现）：失败候选、恢复版本、
  错误摘要与日志路径；处理完故障后删除它。

## 每轮迭代闭环

1. 读 `.supervisor/PROGRESS.md` 与 `state.json`（如有 `RESTART_FAILED.json` 先分析失败原因）。
2. 选择一个明确、可验证的改进；先用 `read`/`grep` 理解相关代码。
3. 实现并自测：`.venv/bin/ruff check src tests` 与 `.venv/bin/python -m pytest -q tests` 必须通过。
4. `git add -A && git commit`。
5. 需要生效时，用独立 tmux session 运行 `.supervisor/restart-supervisor.sh` 重启并验证；
   仅测试/文档变更不需要重启。
6. 更新 `.supervisor/PROGRESS.md`，记录结果、验证方式与下一步。

## 约束

- 不把敏感信息（API Key 等）写入提交或日志；`.env`、`.venv`、`.xsh`、`.supervisor` 均被忽略。
- 不通过删除测试、屏蔽异常或降低检查标准来“修复”问题。
- 保留用户已有修改与会话数据；不要用 `git reset --soft` 当作回滚。
- 重启验证必须基于“关联本次启动”的就绪信号（`--ready-file`）与会话推进，而非旧日志文本。
- 工具文件操作仅在 workspace 内；`.xsh` 预留给会话记录，不要用 shell 绕过该限制。
