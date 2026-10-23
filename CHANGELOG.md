# Changelog

xsh 是一个刻意保持精简的单 Agent harness。以下为自迭代期间的主要成果。

## 工具（agent-visible tools）

- `read` / `write` / `edit`：工作区内读写与字面编辑（read-before-write 策略）。
- `multiedit`：对同一文件按序应用多处编辑，全部匹配时一次性原子写入。
- `glob` / `grep`：路径列举与内容检索；`grep` 支持 `regex`、`ignore_case`、`context`。
- `shell`：前台命令执行（需授权），支持 `cwd`（限工作区内）与超时。
- `todo`：持久化任务清单，支持整体替换与 `add`/`complete`/`remove` 增量维护。
- `task` / `task_status`：子代理委派，可并发多个 `prompts`，或 `background=true` 后台执行后轮询。
- `memory`：跨会话长期记忆（`.xsh/memory.md`），注入系统提示词。
- `skill`：按需加载的可复用 Markdown 技能（`.xsh/skills/*.md`）。
- `web_search` / `web_fetch`：联网检索与抓取，支持 `max_results` / `max_chars`。
- `mcp__<server>__<tool>`：来自 MCP 服务器的外部工具。

## CLI

- `--workspace`、`--session`、`--resume [名字/前缀]`、`--fork`、`--list-sessions`。
- `--dump-prompt`、`--list-tools`、`--list-skills`、`--doctor`、`--compact-session [文件]`。
- `--print`（无终端单轮/非停机执行，prompt 可来自参数或 stdin）。
- `--non-stop-mode`、`--max-turns`、`--max-run-tokens`、`--ready-file`、`--version`。

## 交互命令

`/list` `/find` `/todos` `/memory` `/reload` `/skills` `/tasks` `/usage` `/stats` `/config`
`/sessions` `/export` `/compact` `/doctor` `/help` `/quit`。

## 机制与配置

- 启动就绪信号（`--ready-file`）与外置重启监督脚本（就绪信号 + 会话推进校验、失败回滚）。
- 会话：JSONL 事件流、流式加载、断点修复、自动/手动上下文压缩、离线压缩工具。
- 非停机模式：暂时性错误退避重试、有限次容忍、Turn 上限与 token 预算。
- 工具耗时记录、嵌套 `AGENTS.md`、事件钩子（`.xsh/hooks.json`）、权限策略
  （`.xsh/permissions.json`：`deny_paths`/`deny_commands`/`deny_urls`）。
- MCP 客户端（`.xsh/mcp.json`）与后台子任务。

## 工程实践

- 全部提交信息统一为标准 `<type>: <subject>` 格式。
- `ruff` 干净、193 项测试通过、`scripts/check.sh` 一键自检。
- 每轮改动均经“分析 → 实现 → 测试 → 提交 → 重启 → 验证 → 记录”闭环，重启由监督脚本
  以关联本次启动的就绪信号与会话推进为准提升为 known-good。
