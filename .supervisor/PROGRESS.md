# xsh 自迭代进度记录（持久化，位于 .supervisor/，不受源码回滚影响）

> 每次恢复运行后先读本文件与 `state.json`、`RESTART_FAILED.json`（如有），
> 确认实际运行版本、上一轮结果与监督脚本状态，再继续下一步。

## 交接摘要（最新）
- 已交付 65 项改进，含 7 个大型功能：长期记忆、技能库、事件钩子、预算护栏、
  后台子任务、MCP 客户端、权限策略（需求与调研见 `REQUIREMENTS.md`）。
- 工具：`read` `write` `edit` `multiedit` `glob` `grep` `shell` `todo` `task` `task_status`
  `memory` `skill` `web_search` `web_fetch`（以及 MCP 服务器工具 `mcp__<server>__<tool>`）。
- CLI：`--print`（支持 stdin）、`--compact-session`、`--dump-prompt`、`--list-tools`、
  `--list-sessions`、`--fork`、`--resume [名/前缀]`、`--max-turns`、`--max-run-tokens`、
  `--ready-file`、`--version`。
- 交互命令：`/list` `/find` `/todos` `/memory` `/reload` `/skills` `/tasks` `/usage`
  `/stats` `/config` `/sessions` `/export` `/compact` `/help` `/quit`。
- 质量：`ruff` 干净、202 项测试通过、`scripts/check.sh` 与监督脚本自检 PASS；每轮重启
  均由就绪信号 + 会话推进校验后提升为 known-good（见 `state.json`）。
- 历史：全部提交信息已统一为标准 `<type>: <subject>`（旧历史保留在标签
  `backup-pre-msg-rewrite`）。

## 环境事实（已核实）

- 工作目录 / 仓库根：`/root/xsh-non-stop-mode`
- 用户观察用 tmux session：`xsh`，目标 pane：`%0`（bash `pane_pid=843`）
- 当前 xsh 启动命令：`xsh --non-stop-mode --allow-shell`（前台命令名 `python`）
- 解释器：`/root/xsh-non-stop-mode/.venv/bin/python`；入口脚本 `.venv/bin/xsh`
- `xsh --resume [path]`：省略 path 时恢复 `.xsh/sessions/` 下最近修改的会话；
  给出 path 时恢复指定会话。恢复后若会话记录了 `non_stop_task`，自动进入非停机模式。
- `--resume` 的路径参数必须紧跟其后：`--resume <path> --allow-shell ...`
  （若写成 `--resume --allow-shell <path>`，argparse 会因 nargs="?" 把 path 当成位置 prompt）。
- 监督脚本目录：`.supervisor/`（已被 .gitignore 忽略，`git reset --hard` 与
  `git clean -fd`（不带 -x）都不会删除它）。

## 已核实的基线

- `34af493` = 初始源码快照，tag `known-good-0`，即重启前的可运行版本。
- 该版本**不包含** `--ready-file` 就绪机制与 `continue-prompt` 解析修复。

## 迭代记录

### 第 1 轮（重启执行中）
目标：建立可靠的重启/恢复闭环。
- 初始化 git 仓库并提交基线 `34af493`（tag `known-good-0`）。
- 新增启动就绪信号：`src/xsh/readiness.py` + `xsh --ready-file` 参数 +
  terminal `readiness` 事件。就绪文件含 boot_id / pid / ppid / epoch / session /
  workspace / model / resumed / non_stop，采用临时文件 + os.replace 原子写入。
  已在临时 tmux pane 中端到端验证（含 `--resume <path>` 形态）：就绪文件在模型调用前
  出现、ppid == pane shell PID、会话文件随 Turn 开始增长。
- 修复 `non_stop.py`：正确识别 `<continue-prompt>`（原代码误写为
  `<continue-promot>`，导致续跑块无法拆分），并新增 `from_stored` 兼容旧记录。
- 新增 `tests/`（readiness + non_stop），`ruff` 与 `pytest`（10 项）均通过。
- 新增独立监督脚本 `.supervisor/{lib.sh,restart-supervisor.sh,watchdog.sh}`。
- 修正启动命令参数顺序：`--resume <path> --allow-shell --ready-file <f>`
  （`--resume` 为 nargs="?"，路径必须紧跟其后，否则被当成位置 prompt）。
- **重要环境发现**：`xsh` session 内存在两个窗口（窗口 0 = xsh，窗口 1 是名为
  `watch` 的活动窗口）。`tmux list-panes -t <session>` 只列**活动窗口**的 pane，
  必须用 `tmux list-panes -s -t <session>` 才能列出会话全部 pane。已经据此修正
  `find_target_pane`：优先选择“确实运行着 xsh 进程”的 pane。
- 候选提交 = `68e92e3`（readiness + continue-prompt 修复 + tests）。
- 监督脚本（`.supervisor/`）为 gitignored，不随源码回滚。

本轮重启结果：见 `state.json` 的 `last_status` 与 `logs/supervisor.log`。


## 改进清单（后续轮次，优先级从高到低）

- [x] 建立 git 基线与提交规范
- [x] 启动就绪信号（--ready-file）并验证
- [x] 修复 continue-prompt 解析
- [x] 独立监督脚本 + 保底 watchdog
- [ ] 第 1 轮真实重启并验证（本轮执行）
- [ ] 为工具/会话/agent 增加更多单元测试
- [ ] 会话恢复的健壮性：损坏 JSONL 行的容错与报告
- [ ] 压缩（compaction）边界测试
- [ ] 文档：README 补充非停机与重启监督说明

## 已知问题 / 待观察

- 就绪文件写在 `discover_context_window` 之后：若首次探测网络阻塞，就绪信号会延迟，
  监督脚本以 `XSH_READY_TIMEOUT`（默认 150s）为上限。
- watchdog 仅作为保底，只有“pane 内长时间无 xsh 且监督锁空闲”时才重启。

## 监督脚本用法

```bash
# 一次性重启（由当前 xsh 触发；脚本在独立 tmux session 中运行）：
tmux new-session -d -s xsh-supervisor
tmux send-keys -t xsh-supervisor:0.0 -l 'XSH_RESTART_LABEL=iterN bash /root/xsh-non-stop-mode/.supervisor/restart-supervisor.sh'
tmux send-keys -t xsh-supervisor:0.0 Enter

# 常驻保底看护（独立 session）：
tmux new-session -d -s xsh-watchdog
tmux send-keys -t xsh-watchdog:0.0 -l 'bash /root/xsh-non-stop-mode/.supervisor/watchdog.sh'
tmux send-keys -t xsh-watchdog:0.0 Enter
```

退出码：0 成功；10 失败后已回滚恢复；11 失败且无法恢复（已停止自动重试）；
2 前置条件错误；75 已有监督进程持锁。

## 经验教训（重要）

- **log 不能写 stdout**：`send_launch` 用 `$(...)` 捕获 epoch，曾因 `log` 写 stdout
  把日志文本混入 epoch，导致校验函数抛出、被误判为启动失败（差点误回滚一个可用版本）。
  现已将 `log` 改为 stderr，并增加 `is_epoch` 前置校验，捕获异常即中止而非回滚。
- **`tmux list-panes -t <session>` 只列活动窗口**，必须用 `-s`。会话内可能有多窗口。
- **`pkill -f` 会匹配自身命令行**：曾误杀执行 pkill 的 shell。改用 tmux kill-session
  或 ps 过滤（`restart[-]supervisor` 正则技巧）。
- **频繁 429 会导致进程退出**：provider 有每分钟 token 限制，长会话每步约 14 万 token。
  已在第 2 轮加入暂时性错误重试（进程内退避），避免整进程退出与反复重启。

## 迭代记录（追加）

### 第 2 轮
- 运行中进程曾因 429 RateLimitError 于 07:24:20 退出；watchdog 于 07:25:02 成功恢复
  （证明 watchdog 有效），但旧版 watchdog 的 log-stdout bug 造成校验噪声，已修复。
- 提交 `6daad4c`：agent 分类暂时性错误；non_stop 退避重试；model 限制 429 建连重试；
  terminal 增加 retry 提示；新增 5 项测试（共 15 项通过，ruff 干净）。
- 待办：用修复后的监督脚本重启并验证本提交。
- 已验证：监督脚本 iter2 成功，`6daad4c` 提升为 known-good（state.last_status=ok，
  supervisor 退出码 0），新进程就绪信号与会话推进均通过。

### 第 3 轮
- 提交 `78b131a`：会话加载容错——末尾被中断的半行 JSON 会被丢弃并物理截断，
  保证中断的会话仍可恢复；同时修复“完整记录缺末尾换行”的情况。
- 新增 tests/test_session.py（共 20 项测试通过，ruff 干净）。
- 已验证：iter3 成功，`78b131a` 提升为 known-good（status ok，退出码 0）。

### 第 4 轮
- 提交 `8cee27c`：新增 tests/test_compaction.py（estimate、参数校验、手动压缩、
  pending 保护），共 28 项测试通过。仅测试，无需重启。

### 第 5 轮
- 提交 `7561836`：新增 `AGENTS.md`（把重启/监督闭环与约束写入项目指令，
  每次恢复自动生效）并更新 README。
- 已验证：iter5 成功，`7561836` 提升为 known-good；系统提示词已包含 AGENTS.md。

### 第 6 轮
- 提交 `3aa924c`：修复 `tools/base.bounded()` 在 limit 小于截断提示时仍可能超过
  limit 的问题（当 limit <= 提示长度时只返回提示的前 limit 个字符）。
- 新增 tests/test_config.py、tests/test_tools_base.py（共 46 项测试通过，ruff 干净）。
- 已验证：iter6 成功，`3aa924c` 提升为 known-good（status ok，退出码 0）。

### 第 7 轮
- 提交 `9469383`：model 建连阶段除 429 外，也重试连接错误/超时（仅在尚未产生
  任何输出之前重试，避免重复输出）；新增 tests/test_model.py。
- 共 49 项测试通过，ruff 干净。待办：重启验证本提交。
- 已验证：iter7 成功，`9469383` 提升为 known-good（status ok，退出码 0）。

### 第 8 轮
- 提交 `71989ee`：会话日志不再逐步落盘完整请求体（原实现每步重复写入全部历史，
  造成文件 O(n^2) 膨胀、拖慢恢复），改为记录 `{step, messages, tools}` 摘要；
  压缩日志同样改为只记消息数。
- 新增 tests/test_agent.py（共 51 项测试通过，ruff 干净）。待办：重启验证本提交。
- 已验证：iter8 成功，`71989ee` 提升为 known-good（status ok，退出码 0）。

### 第 9 轮
- 提交 `adb01a9`：`_read_events` 改为逐行流式读取并按字节偏移截断残片，
  降低超大会话文件的峰值内存；语义与测试保持一致。
- 已验证：iter9 成功，`adb01a9` 提升为 known-good（status ok，退出码 0）。

### 第 10 轮
- 提交 `7fbcb1a`：新增 tests/test_files.py（工作区限制、读后写约束、
  edit 唯一匹配/替换全部、二进制拒绝、glob/grep）。共 59 项测试通过。
- 仅测试，无需重启。

## 改进清单（更新）

- [x] 建立 git 基线与提交规范
- [x] 启动就绪信号（--ready-file）并验证
- [x] 独立监督脚本 + 保底 watchdog（多轮真实验证）
- [x] 非停机模式容忍暂时性故障（429/超时/连接错误）
- [x] 会话恢复容错与流式读取
- [x] 修复会话文件 O(n^2) 膨胀
- [x] 覆盖 config/prompt/tools/compaction/model/agent/session/files 的单元测试
- [x] 压缩的自动触发路径测试（达到阈值时的端到端压缩）
- [x] shell 工具测试（执行、退出码、工作目录、超时）
- [x] web 工具测试（URL/IP 校验、搜索解析、HTML→Markdown、格式化/截断）
- [ ] 压缩对超长单 Turn 的行为与边界
- [ ] 视需要压缩超大的既有会话文件（保留备份）

## 迭代记录（续）

### 第 11 轮
- 提交 `b6be95d`：新增“达到阈值时自动压缩”的测试。共 60 项测试通过。

### 第 12 轮
- 监督脚本 `restart-supervisor.sh`（gitignored）加固：验证“pane 下恰好一个 xsh 进程”，
  并在成功时记录/核对运行中的源码提交（HEAD==candidate）。
- 已验证：iter12 成功，`running_commit` 与候选一致，退出码 0。

### 第 13 轮
- 提交 `bbba754`：新增 tests/test_shell.py。共 65 项测试通过。仅测试，无需重启。

### 第 14 轮
- 提交 `56a5b20`：新增 tests/test_prompt.py（含 AGENTS.md 越界符号链接拒绝）。共 70 项测试通过。

### 第 15 轮
- 提交 `ed57fc8`：恢复会话时统计并提示补齐的未完成工具调用（`repair_pending` 返回数量，
  新增 terminal `recovery` 事件）。
- 已验证：iter15 成功，`ed57fc8` 提升为 known-good（status ok，退出码 0）。

### 第 16 轮
- 提交 `59f3cef`：新增 tests/test_web.py（URL/IP 校验、搜索解析、HTML→Markdown、
  搜索/抓取格式化与截断）。共 95 项测试通过。仅测试，无需重启。
- 当前已知良好提交：见 state.json（每轮重启成功后更新）。

### 第 17 轮
- 提交 `626974e`：pyproject 增加 pytest 配置（testpaths），`.env.example` 补充可选运行时设置。
- 已验证：iter17 成功，`626974e` 提升为 known-good（status ok，退出码 0）。

### 第 18 轮
- 提交 `73c329b`：新增压缩边界测试（超长单 Turn 内保持工具调用配对；历史不足时返回 None）。
- 共 97 项测试通过，ruff 干净。

### 现状小结（供恢复后快速接手）
- 已知良好提交与运行版本：`.supervisor/state.json` 的 `good_commit` / `running_commit`。
- 监督脚本：`.supervisor/restart-supervisor.sh`（一次性重启）与 `watchdog.sh`（保底）。
- 测试：`cd /root/xsh-non-stop-mode && .venv/bin/ruff check src tests && .venv/bin/python -m pytest`。
- 每轮：实现→测试→提交→（如需）用独立 tmux session 重启验证→更新本文件。

### 第 19 轮
- 提交 `8f29634`：注册 SIGTERM 处理，转为 KeyboardInterrupt，复用 Ctrl+C 收尾路径
  （强制停止时仍修复未完成调用并记录 turn_end）。已在临时 pane 冒烟验证干净退出。
- 已验证：iter19 成功，`8f29634` 提升为 known-good。

### 第 20 轮
- 提交 `3e3c26f`：启动阶段收到 Ctrl+C/SIGTERM 时干净退出（返回 130，不打印栈）。
- 已验证：iter20 成功，`3e3c26f` 提升为 known-good（status ok，退出码 0）。

### 当前状态（第 21 轮后）
- 已知良好且有运行版本：`6b427f0`（`state.json` 的 `good_commit` == `running_commit`）。
- 测试：99 项通过；`ruff check src tests` 干净。
- 反复验证：多轮 C-c + 就绪信号 + 会话推进校验的重启均成功；一次 429 导致的意外退出
  由 watchdog 自动恢复。

### 第 21 轮
- 提交 `6b427f0`：非停机模式下，非暂时性错误不再立即结束进程，而是有限次
  （`_MAX_CONSECUTIVE_FAILURES=5`，间隔 `_FAILURE_BACKOFF_SECONDS=10`）继续后续 Turn，
  只有持续失败才退出交给监督脚本。
- 已验证：iter21 成功，`6b427f0` 提升为 known-good（status ok，退出码 0）。

### 第 22 轮
- 新增 `.supervisor/selftest.sh`：监督脚本纯函数离线自检（is_epoch、启动命令顺序、
  ready_ok、is_xsh_pid、pane 识别），全部 PASS；并在 `AGENTS.md` 记录重启前先跑它。
- 提交 `2b1dec0`（AGENTS.md）。仅文档/工具，无需重启。

### 第 23 轮
- 提交 `5ad0992`：就绪记录附加会话进度（`turns`/`messages`），便于监督脚本与人工
  确认“恢复成功”。新增对应测试（共 100 项通过）。
- 已验证：iter23 成功，`5ad0992` 提升为 known-good；`ready.json` 含 turns=18/messages=644。

### 第 24 轮
- 提交 `ca778a3`：新增 tests/test_messages.py（消息/工具调用校验与 wire 转换）。共 108 项通过。

### 第 25 轮
- 提交 `35562db`：新增“压缩检查点重放”测试（摘要位置为 None、不增加轮次、后段保留）。
  共 109 项通过。仅测试。
- 注：第 12 轮为监督脚本（gitignored）加固，无提交。
- 已验证：iter25 合并重启成功，`35562db` 提升为 known-good（status ok，退出码 0）。

### 第 26 轮
- 提交 `735cf7e`：修正 cli.py 阶段编号（1–7 一致）。仅注释，无需重启。
- 累计 109 项测试通过，ruff 干净，监督脚本自检全通过。

### 第 27 轮
- 提交 `1a6c6c8`：README 参数表补充 `--non-stop-mode` 与 `--ready-file`。仅文档。

### 第 28 轮
- 提交 `d7c5de3`：新增离线会话压缩工具 `xsh.maintenance`（黑名单丢弃冗余诊断事件、
  临时文件重建 + 加载校验、保留 `.bak` 备份），并为 `Session.load` 增加 `repair` 开关；
  监督脚本支持可选 `XSH_COMPACT_SESSION=1`，在停止窗口执行压缩。共 112 项测试通过。
- 已验证：iter28 开启压缩重启成功，`d7c5de3` 提升为 known-good；实时会话
  文件由 102.7MB 缩减到 1.46MB（恢复更快），重启后仍 turns=20/messages=724。
- 已删除已验证无用的 100MB `.bak`。

### 第 29 轮
- 提交 `e6ba0d1`：新增 `--version`，并固定 argparse prog 为 `xsh`（帮助/版本输出稳定）。
  共 113 项测试通过。
- 已验证：iter29 成功，`e6ba0d1` 提升为 known-good（status ok，退出码 0）。
- 会话文件维持 ~1.5MB（第 8 轮的 O(n^2) 修复生效，增长恢复为线性）。

## 下一步候选（按价值排序）
1. 端到端测试：非停机模式下暂时性错误的实际退避重试（需网络桩）。
2. 继续小步加固与文档完善。
3. 定期复核整条重启闭环（每轮重启即验证一次）。

### 第 30 轮
- 提交 `d06638e`：新增 tests/test_terminal.py，通过注入强制终端 Console 覆盖
  terminal 事件渲染、outcome 与 history。共 116 项测试通过，ruff 干净。仅测试。

## 用户留言（已处理，第 31 轮）

项目根目录的 `message-from-human-read-then-delete` 内容：
**“请不要‘沉迷’于编写测试代码，编写新功能是任务的核心重点。”**

据此调整方向：**以新功能为主**，测试仅做必要覆盖。

- 已读取留言并按留言要求执行；已删除留言文件，并移除 AGENTS.md 中“用户留言”那行；
  `.gitignore` 增加 `message-from-human-read-then-delete` 与 `*.swp`（提交 `8fd17dd`）。
- 第 31 轮同时修复了监督脚本自动提交把留言/临时文件纳入提交的问题来源（改为忽略）。

## 新功能轮次（按用户要求）

### F1 任务清单工具 `todo`（提交 `37b6b58`，已验证，good）
- 新增 `src/xsh/tools/todo.py`：模型提交完整清单，工具写入会话（`todos` 事件）并在终端渲染。
- 会话恢复时重放清单，跨重启续作；`Session.todos` 持久化。
- 已注册进默认工具集；README 记录。重启验证通过。

### F2 grep 增强（提交 `9265da6`，已验证，good）
- `GrepArgs` 新增 `regex` / `ignore_case` / `context`（0–3）；默认仍为字面匹配。
- 输出上下文行用 `-` 分隔（`file-line- text`），匹配行用 `:`。
- 更新工具描述与指导文案。重启验证通过。

### F3 子代理委派 `task`（提交 `00b2c84`，已验证，good）
- 新增 `src/xsh/tools/task.py`：把自包含子任务交给独立上下文的子代理（独立会话、
  复用 default 工具集因而不含 task，避免递归），返回最终报告。
- `ToolRegistry.add()` 在构建系统提示词前追加工具；cli 调整顺序（先建模型与委派工具，
  再构建提示词）。
- 子会话写入 `.xsh/subtasks/`（gitignored）。重启验证通过，系统提示词含 task/todo 指导。

## 下一步候选（以新功能为主）
1. 会话列表与选择（`--list-sessions` 或交互式 `/sessions`）。
2. 子代理并行/后台委派（当前为前台同步）。
3. 文件工具：多文件批量编辑 / apply-patch 风格变更。
4. 交互式命令增强（`/find`、`/usage`）。

### F4 会话列表 `--list-sessions`（提交 `687a2c1`，已验证，good）
- cli 新增 `--list-sessions`（创建 Terminal 之前处理，可脚本化）与 `list_sessions()`。

### F5 清单可见性与交互命令（提交 `4526b7f`，已验证，good）
- 恢复后展示持久化清单；交互命令 `/todos` 与 `/find <text>`（`Terminal.find`）。

### F6 批量编辑 `multiedit`（提交 `18526f4`，已验证，good）
- 对同一文件按序应用多处字面编辑，全部匹配时一次性原子写入。

### F7 `/usage`（提交 `24323fd`，已验证，good）
- `session.usage_totals()` + `Terminal.usage()` + `/usage` 命令。共 131 项测试。

### F8 会话分叉 `--fork`（提交 `77795da`，已验证，good）
- `fork_session()` 复制会话为新文件后按恢复打开，原会话不受影响；README 参数表更新。

### F9 并发子代理（提交 `e9b45c2`，已验证，good）
- `task` 工具支持 `prompts`（最多 4 个）并发执行（ThreadPoolExecutor），返回合并报告。
- 子代理不向终端输出，避免竞争；共 134 项测试。

### F10 `/help`、`/sessions`（提交 `695a296`，已验证，good）
- 交互命令补齐：`/help` 打印帮助，`/sessions` 列出工作区会话；共 135 项测试。

### F11 `--max-turns`（提交 `d8951b0`，已验证，good）
- 非停机模式下限制 Turn 数，达到后正常停止（返回 0）；config 增加 `max_turns`（XSH_MAX_TURNS）。
- 共 137 项测试；README 与 .env.example 同步。

### F12 嵌套 AGENTS.md（提交 `f49b51d`，已验证，good）
- `build_prompt` 收集子目录 `AGENTS.md`（带相对路径、限量 20、跳过 .git/.xsh 等），
  作为 `context:project:<path>` 段加入提示词；共 139 项测试。

### F13 `web_search` max_results（提交 `5fbf409`，已验证，good）
- 搜索工具新增 `max_results`（1–8）；共 140 项测试。

### F14 `--dump-prompt`（提交 `ff12383`，已验证，good）
- 打印组装后的系统提示词并退出（无需终端/模型）；settings 解析抽成 `_settings_from_args()`。
- 共 141 项测试。

## 当前状态
- 已知良好与运行版本：见 `state.json`（每轮重启后更新为 `running_commit`）。
- 工具集：read/write/edit/multiedit/glob/grep/shell/todo/task/web_search/web_fetch。
- 交互命令：`/list` `/find` `/todos` `/usage` `/sessions` `/help` `/compact` `/quit`。
- 累计 144 项测试通过；`ruff check src tests` 干净；监督脚本自检全通过。

### F15 工具耗时记录（提交 `8f6417d`，已验证，good）
- 每次工具执行追加 `tool_end` 事件（id/name/seconds/chars），便于事后诊断。

### F16 shell `cwd`（提交 `a257be6`，已验证，good）
- `shell` 支持工作区内子目录作为工作目录；越界或不存在则报错。共 144 项测试。

### F17 `--list-tools`（提交 `d00fd19`，已验证，good）
- 打印可用工具及其说明并退出（与 `--dump-prompt` 共用早期分支）；共 145 项测试。
- 注意：本轮重启在 22s 等待窗口内被我自己的 shell 命令打断，随后确认监督脚本
  仍独立完成健康检查并提升 `d00fd19` 为已知良好（无需人工干预）。

### F18 `web_fetch` max_chars（提交 `91c6edb`，已验证，good）
- 抓取工具新增 `max_chars`（1_000–上限）；共 146 项测试。

### F19 `--resume` 名称前缀（提交 `ede3eeb`，已验证，good）
- `resolve_session()`：`--resume <名字/前缀>` 在会话目录内解析，多个匹配取最新；
  共 147 项测试。

## 功能总览（截至 F29）
- 工具：`read` `write` `edit` `multiedit` `glob` `grep`(regex/ignore_case/context) `shell`(cwd)
  `todo`(替换 / `add` / `complete` / `remove`) `task`(并发 `prompts`；`background` + `task_status`)
  `memory`(长期记忆) `skill`(按需技能) `web_search`(max_results) `web_fetch`(max_chars)
  以及来自 MCP 服务器的 `mcp__<server>__<tool>`。
- 交互命令：`/list` `/find` `/todos` `/memory` `/skills` `/usage` `/stats` `/sessions` `/help` `/export` `/compact` `/quit`。
- CLI：`--workspace` `--session` `--resume [名/前缀]` `--fork` `--list-sessions` `--dump-prompt`
  `--list-tools` `--non-stop-mode` `--max-turns` `--max-run-tokens` `--ready-file` `--version`。
- 机制：就绪信号、会话修复/压缩、非停机重试与上限、工具耗时记录、嵌套 AGENTS.md、
  钩子、长期记忆、技能库、后台子任务、MCP 客户端。
- 验证：`ruff check src tests` 干净；172 项测试通过；监督脚本自检 PASS；每轮重启
  均由就绪信号 + 会话推进校验后提升为 known-good。

### F20 增量 todo 操作（提交 `e740cde`，已验证，good）
- `todo` 支持 `add`/`complete`/`remove`，并可整体替换或清空；`Session.record("todos")`
  同步更新内存清单，工具执行期间即可读到最新状态。共 149 项测试。

### F21 `/export`（提交 `281241a`，已验证，good）
- `transcript.render_transcript`/`export_transcript` 把对话写成 Markdown；`/export [文件]`
  限制在工作区内；共 151 项测试。

### F22 `/stats`（提交 `ddd7765`，已验证，good）
- 会话概览：轮次/消息数/工具调用数/清单项/总 token；共 152 项测试。

### F24 长期记忆子系统（提交 `6feb6f5`，已验证，good；大功能）
- `xsh/memory.py`（`MemoryStore` → `.xsh/memory.md`）+ `memory` 工具（add/replace/remove）+
  提示词 `context:memory` 段 + `/memory`；子代理共享同一记忆；端到端已实机验证。

### F25 技能库（提交 `8ec883c`，已验证，good；大功能）
- `xsh/skills.py`（`SkillLibrary` → `.xsh/skills/*.md`）+ `skill` 工具（渐进式披露）+
  提示词 `context:skills` 索引 + `/skills`；工具数增至 11；共 161 项测试。

### F26 事件钩子（提交 `cec61d0`，已验证，good；大功能）
- `xsh/hooks.py`：`.xsh/hooks.json` 的 pre/post tool-use 钩子（需启用 shell）；
  pre 非零退出拦截调用并记录 `hook` 事件；共 166 项测试。

### F27 预算护栏（提交 `0c18e9f`，已验证，good）
- `--max-run-tokens` / `XSH_MAX_RUN_TOKENS`：非停机模式累计 token 达标即正常停止；
  共 169 项测试。

### F28 后台子任务（提交 `1a1c8f2`，已验证，good；大功能）
- `task` 支持 `background=true` 返回句柄，新增 `task_status` 工具轮询；
  cli 用线程 + 锁维护后台任务表；共 171 项测试。

### F29 MCP 客户端（提交 `1517a62`，已验证，good；大功能）
- `xsh/mcp.py`：`.xsh/mcp.json` 的 stdio 服务器，行分隔 JSON-RPC 握手，
  `tools/list`/`tools/call`；`tools/mcp.py` 把其工具注册为 `mcp__<server>__<tool>`
  （`Tool.schema_override` 透传服务器 schema）；失败优雅降级；共 172 项测试。
- 至此 REQUIREMENTS.md 的 1–6 号大功能全部完成。

### F30 dump-prompt 与真实提示词对齐（提交 `7576fa1`，已验证，good）
- 早期 `--dump-prompt`/`--list-tools` 现补齐 `task`/`task_status`（占位回调），
  输出与真实运行的工具集/提示词一致；重启时离线压缩会话（3.38MB→3.25MB）。

### F31 `/config` 运行配置概览（提交 `b9e05f1`，已验证，good）
- 展示 model/base_url/workspace/context_window/预算/记忆/技能/MCP/钩子状态；共 172 项测试。

### F32 MCP 读超时（提交 `1ba8d75`，已验证，good）
- `McpClient._read_response` 用 `select` 加读超时，挂起的服务器会超时被跳过而不阻塞 xsh；
  共 173 项测试。

### F33 `/tasks` 与 MCP 连接报告（提交 `c78c6a6`，已验证，good）
- `/tasks` 列出后台子任务；配置了 MCP 服务器时报告 `已连接/总数`，便于诊断。
- README 增补交互命令表。

### F34 终端/ MCP 健壮性小修（提交 `2a20e9f`，已验证，good）
- `Terminal.report` 未知事件类型改为暗色打印（不再静默丢弃）；MCP `select` 仅在 POSIX 使用。
- 共 174 项测试。

### F35 `--print` 无终端模式（提交 `0a98e10`，已验证，good）
- 给定 prompt 直接执行并打印结果（支持 `--resume`/`--fork`/`--non-stop-mode`），便于脚本化；
  不启动子代理；实机冒烟 `--print "…pong"` 输出 `pong` 且退出码 0；共 175 项测试。

### F36 `/reload`（提交 `75c9068`，已验证，good）
- `MemoryStore.reload()` + `/reload`：外部编辑记忆/技能后无需重启即可生效；共 176 项测试。
- 说明：README 命令表在下一轮补入 `/reload`。

### F37 `--compact-session` CLI（提交 `7b6f99e`，已验证，good）
- `xsh --compact-session [文件]` 离线压缩会话并打印统计（默认最近会话）；共 178 项测试。

### F38 抽离 BackgroundJobs（提交 `9172728`，已验证，good）
- 新增 `xsh/background.py`（线程 + 锁，含耗时上报），cli 复用；补 4 项单元测试；
  共 182 项测试。

### F39 子任务健壮性（提交 `d0ebd80`，已验证，good）
- 单个子任务失败不再中断整批（返回错误文本）；后台子代理静默，避免与主界面竞争。

### F40 子任务报告含子会话名（提交 `d8c481d`，已验证，good）
- task 报告附带 `[session <name>]`，便于定位子代理的 `.xsh/subtasks/*.jsonl`。

### F41 `--print` 支持标准输入（提交 `edc56c5`，已验证，good）
- `echo "…" | xsh --print` 从 stdin 读取 prompt；实机冒烟输出 `pong2`、退出码 0；共 183 项测试。

### F42 修正 `--print` 的记忆/技能路径（提交 `c8905ef`，已验证，good）
- 记忆/技能库改为在确定最终 workspace（可能来自恢复的会话）之后再创建，避免指向错误目录。

### F43 `--print` 自动压缩对齐（提交 `a6de5a5`，已验证，good）
- `--print` 同样挂载 Compactor（当上下文窗口已知时启用自动压缩），与交互模式一致。

### F44 记忆条目编号（提交 `08ede19`，已验证，good）
- `MemoryStore.render_numbered()`：工具输出与 `/memory` 带 1-based 序号，便于 remove；
  共 183 项测试。

### F45 权限策略（提交 `c513b67`，已验证，good；大功能）
- `xsh/permissions.py` + `.xsh/permissions.json`：`deny_paths` 阻止读写、`deny_commands`
  阻止命令；FileTools/ShellTools 接入；共 187 项测试。

### F46 `deny_paths` 覆盖读取（提交 `98ce014`，已验证，good）
- 读取 `.env` 等敏感路径也会被权限策略拒绝（此前只拦写入）。

### F47 权限策略覆盖检索（提交 `732f8ae`，已验证，good）
- `glob`/`grep` 结果会跳过被 `deny_paths` 拒绝的路径，避免经检索泄露；共 189 项测试。

### F48 `/config` 显示权限摘要（提交 `8741021`，已验证，good）
- `Permissions.summary()`；`/config` 增加 permissions 行，便于确认策略已加载。

### F49 `/sessions` 标记当前会话（提交 `5ed6cea`，已验证，good）
- 列表中以 `*` 标出当前会话；共 189 项测试。

### F50 `deny_urls` 权限（提交 `2506a5d`，已验证，good）
- 权限策略扩展：`deny_urls` 拒绝抓取并过滤搜索来源；共 190 项测试。

### F51 `/usage` 显示上下文窗口（提交 `0242b7d`，已验证，good）
- 已知上下文窗口时在用量面板中显示，便于评估压力；共 190 项测试。

### F52 `--print` 中断干净退出（提交 `6683ed4`，已验证，good）
- `--print` 捕获 KeyboardInterrupt/SIGTERM 返回 130，不打印堆栈；重启时再次离线压缩会话
  （4.25MB→4.10MB），校验后删除 .bak。

### F53 `--list-skills`（提交 `3e9ca00`，已验证，good）
- CLI 列出工作区技能（与 `--list-tools` 并列）；共 191 项测试。

### F54 `/find` 覆盖工具参数（提交 `ef8bd91`，已验证，good）
- 查找同时匹配消息内容与工具调用的名称/参数；共 192 项测试。

### F55 `XSH_ALLOW_SHELL` 环境变量（提交 `b85d975`，已验证，good）
- 置 1/true 时无需 `--allow-shell` 即启用 shell；`_allow_shell()` 统一判定；共 193 项测试。

### F56 `deny_paths` 支持相对路径（提交 `60301ce`，已验证，good）
- 权限策略同时匹配绝对路径、文件名与工作区相对路径，`secrets/**` 等写法生效；共 194 项测试。

### F57 `/stats` 显示会话文件大小（提交 `2075f3d`，已验证，good）
- 概览面板新增 Session file 行，便于判断是否该压缩；共 194 项测试。

### F58 `todo` 支持只读查看（提交 `c537169`，已验证，good）
- 空调用 `todo` 返回当前清单（不改动），便于恢复后确认清单；共 195 项测试。

### F59 `/reload` 刷新权限（提交 `15faeee`，已验证，good）
- `Permissions.reload()` 就地重读源文件（工具持有同一引用），`/reload` 一并刷新；共 197 项测试。

### F60 `/config` 显示 shell 状态（提交 `fdc1478`，已验证，good）
- 概览行增加 `shell: on/off`，便于确认当前是否启用命令执行。

### F61 `/export` 追加清单与记忆（提交 `bdd91e0`，已验证，good）
- 导出转录末尾追加 Todos/Memory 小节（`render_transcript(..., extra_sections=)`）；共 198 项测试。

### F62 未知技能的报错更友好（提交 `e4fcabc`，已验证，good）
- `Unknown skill` 报错附带可用技能名，便于模型自我纠正；共 198 项测试。

### F63 `/help` 补充配置文件（提交 `bf3ebb8`，已验证，good）
- 帮助文本新增配置文件小节，并同步 `/reload`、`/export` 的说明。

### F64 `--doctor` / `/doctor` 环境自检（提交 `b4b5cf9`，已验证，good）
- 新增只读自检（工作区可写、模型/密钥、上下文窗口、shell、hooks/mcp/permissions 解析、
  技能与记忆）；CLI `--doctor` 与交互 `/doctor`；共 201 项测试。

### F65 doctor 退出码 + 监督就绪检查（提交 `1b593a8`，已验证，good）
- `--doctor` 存在 fail 时返回 1；重启监督脚本在健康检查中运行 `--doctor` 并记录
  “doctor check passed”（非致命）；共 202 项测试。



### F23 会话自动压缩（提交 `a77122e`，已验证，good）
- `XSH_SESSION_COMPACT_MB`（默认 0=关闭）启用后，恢复时超过阈值即离线压缩；共 153 项测试。

### F24 长期记忆子系统（大功能；需求见 REQUIREMENTS.md）
- 新增 `xsh/memory.py`（`MemoryStore`，`.xsh/memory.md`）与 `memory` 工具
  （add/replace/remove）；系统提示词新增 `context:memory` 段；`/memory` 查看；
  子代理共享同一记忆；共 157 项测试。
- 已按用户留言调研当前 Agent 框架（Claude Code / OpenHands / Cursor / Aider），
  把“更大功能”需求与路线图写入 `.supervisor/REQUIREMENTS.md`，随后删除该留言行。

## 维护记录
- 结论：会话压缩与监督脚本健康检查的相互作用 —— 监督脚本按“会话文件大小增长”判定恢复成功，
  而 `XSH_SESSION_COMPACT_MB` 会在恢复时**缩小**该文件。因此默认保持关闭，重启时改用
  监督脚本的 `XSH_COMPACT_SESSION`（在停止窗口内压缩，尺寸在两次校验之间一致）。
- 2026-10-23T10:36Z：处理用户留言（要求统一全部历史提交信息），完成后已删除该留言行。
  以标准 `<type>: <subject>` 格式（feature/fix/docs/test/perf/chore）重写 54 个提交；
  代码树与重写前完全一致（`git diff --stat` 为空）；旧历史保留在标签
  `backup-pre-msg-rewrite`；`.supervisor/state.json` 已指向新 HEAD `6348023`，重启后
  监督脚本提升 `6348023` 为 known-good；全部提交信息经校验均为标准格式。
- 2026-10-23T10:24Z：以 `XSH_COMPACT_SESSION=1` 重启，停止窗口内离线压缩会话
  （2,568,177 → 2,414,753 字节，保留 .bak），随后新进程就绪并通过健康检查；
  校验后删除 .bak。当前会话文件 2,431,282 字节 / 2246 行，全部为合法 JSONL。


























