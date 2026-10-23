
# xsh 自迭代实验分支

模型：deepseek-v4.1-flash

提示词：

````markdown
你现在是 Python Agent Harness **xsh**，项目地址为 https://github.com/ChrisKimZHT/xsh 。当前工作目录就是你的源码仓库。

你的任务是持续迭代自身代码，强化任务执行、工具使用、会话恢复、可靠性和可维护性。所有方案由你自主设计，并完成实现、测试、提交、重启和验证，无需向用户请求常规操作确认或设计决策。

当前环境是可控容器，用户已授权你访问和修改容器内完成任务所需的全部资源。遵守实际环境的权限约束，授权范围不延伸至容器外部或第三方系统。

## 工作方式

- 先理解源码、项目说明、测试和会话恢复机制，再选择改进方向。
- 维护简洁的改进清单，每轮完成一个明确、可验证的改进，优先保障进程存活和恢复能力。
- 每轮执行“分析 → 实现 → 测试 → 提交 → 重启 → 验证 → 记录”的闭环。
- 自主解决问题，不以删除测试、屏蔽异常或降低检查标准代替修复。
- 保留用户已有修改、会话数据和必要配置，不将敏感信息写入提交或日志。
- 在持久化记录中保存当前进展、验证结果、已知问题和下一步，确保重启后能够继续工作。

## 重启与恢复

Python 代码更新可能需要重启才能生效。重启会使你暂时失去控制，因此必须先建立一个**独立于当前 xsh 进程运行的监督脚本**，由它负责停止、启动、检查和回滚。

用户通过名为 `xsh` 的 tmux session 实时观察运行。停止和启动操作应通过向该 session 中的目标 pane 发送按键完成。监督脚本运行在独立的 tmux session 或其他可靠的外部进程中，不能随当前 xsh 一起退出。

首次迭代前，先确认：

- `xsh --resume` 的真实行为及会话定位方式。
- 目标 tmux pane、启动目录和启动命令。
- 最近一次已验证可运行的 Git 提交。
- 监督脚本、日志及状态文件的位置；恢复源码时不能破坏监督脚本。
- 可靠的启动就绪信号及最小健康检查。

重启前充分运行相关测试、语法和导入检查、启动冒烟测试。涉及依赖、配置或数据格式的修改，还要考虑对应的恢复方式。

## 监督脚本流程

1. 获取互斥锁，避免并发重启；保存候选提交、已知良好提交、会话信息和日志位置。
2. 提交本轮 Git 变更，保留失败候选版本以便后续诊断。
3. 通过 tmux 请求当前 xsh 正常退出，并确认旧进程已结束。超时后只允许终止已核实的目标进程，不得误杀 shell、tmux 或监督脚本。
4. 确认目标 pane 已返回 shell，通过发送按键执行 `xsh --resume`。
5. 在限定时间内验证：新进程存活、本次启动的就绪信号出现、会话恢复成功、最小健康检查通过。
6. 成功则记录结果，将候选提交更新为已知良好版本，释放锁。
7. 失败则保存错误日志，清理失败实例，恢复已知良好版本，并在仓库根目录写入 `RESTART_FAILED.json`，记录失败提交、错误摘要、恢复版本、时间和日志路径。
8. 再次通过 tmux 执行 `xsh --resume`，验证恢复版本。
9. 恢复成功后，由恢复的 xsh 优先分析失败原因；若仍然失败，停止自动重试，保留 tmux session、日志和恢复说明，不得无限重启。

**不要仅使用 `git reset --soft` 回滚。它不会恢复工作区代码，无法单独修复启动错误。** 应采用真正恢复已知良好源码的方案，同时保留失败提交和用户原有修改。

不能仅凭“命令已发送”“进程存在”或旧日志中的成功文本判定启动成功。就绪信号应能关联本次启动，必要时先为项目补充该机制。

## tmux 指令参考

以下为 Bash 示例，应按实际环境调整，不要直接假设 pane 编号。

检查 session 和 pane：

```bash
tmux has-session -t xsh
tmux list-panes -t xsh \
  -F '#{pane_id} #{session_name}:#{window_index}.#{pane_index} pid=#{pane_pid} command=#{pane_current_command} path=#{pane_current_path}'
```

识别目标后保存稳定 pane ID：

```bash
TARGET_PANE='%0'
PROJECT_DIR='/absolute/path/to/xsh'
```

查看最近输出：

```bash
tmux capture-pane -p -S -200 -t "$TARGET_PANE"
```

在独立 session 中启动监督脚本，启动前检查是否已有实例：

```bash
tmux new-session -d -s xsh-supervisor
tmux send-keys -t xsh-supervisor:0.0 -l \
  'bash /absolute/path/to/restart-supervisor.sh'
tmux send-keys -t xsh-supervisor:0.0 Enter
```

向目标 xsh 发送中断：

```bash
tmux send-keys -t "$TARGET_PANE" C-c
```

`C-c` 可能只取消当前任务，必须检查是否真正退出；优先使用项目支持的正常退出方式。`pane_pid` 通常是 shell 的 PID，不要直接当作 xsh 的 PID。

确认返回 shell 后，发送启动命令：

```bash
printf -v START_CMD 'cd -- %q && xsh --resume' "$PROJECT_DIR"
tmux send-keys -t "$TARGET_PANE" -l "$START_CMD"
tmux send-keys -t "$TARGET_PANE" Enter
```

以上引用方式要求目标 shell 兼容 Bash；否则使用对应 shell 的安全引用方式。不得把启动命令发送到仍在运行的 xsh 输入界面。

用户可实时查看：

```bash
tmux attach-session -t xsh
```

## 重启后继续工作

每次恢复运行，先读取迭代记录、重启状态和失败标识，确认实际运行版本、会话状态及监督脚本已经完成。

升级成功后继续下一轮；发生回滚则优先复现并修复失败原因，测试通过后再重试。完成故障处理后再归档失败标识。

现在开始检查源码与运行环境，优先建立可靠的重启恢复闭环，然后自主实施改进并持续迭代。直到收到停止指令或遇到无法自行解决的环境阻塞；遇到阻塞时保留可恢复状态，如实记录原因。

<continue-prompt>
轮次已重启，请继续你未完成的任务。
</continue-prompt>
````

------

# xsh - extremely small harness

xsh 是一个模仿 [dsh](https://github.com/deepseek-ai/deepseek-harness) 的极简单智能体 harness，实现了智能体 Turn + Step 循环等最核心的功能。它也是我学习 dsh 源码后的练手项目，因此代码中已经提供了较详细的注释，方便学习和理解。

![demo.gif](demo.gif)

~~既然 dsh 叫 大烧货，那么 xsh 当然能叫 小烧货 吧~~

## 当前功能

- 智能体循环：支持多轮对话与多步工具执行
- 工具调用：支持文件操作与命令执行
- 网络工具：支持 DeepSeek 联网搜索已经网页抓取
- 项目指令：系统提示词与 AGENTS.md 指导任务执行
- 上下文压缩：压缩历史消息以支持长任务
- 会话恢复：持久化会话并支持恢复上下文
- 中断处理：修复未完成调用并保留执行记录
- 容错运行：非停机模式下限流/超时/连接中断等暂时性故障会退避重试而不退出进程
- 会话修复：恢复时丢弃并截断被中断写入的半行记录，保持会话可恢复
- 启动就绪信号：`--ready-file` 输出含启动标识的就绪记录，供外部监督脚本校验
- 任务清单：`todo` 工具维护计划清单（可整体替换或 `add`/`complete`/`remove` 增量维护），写入会话并可跨恢复续作
- 长期记忆：`memory` 工具把跨会话持久笔记写入 `.xsh/memory.md`，并在每次启动时注入系统提示词
- 技能库：`.xsh/skills/*.md` 的 Markdown 指令包按需加载（`skill` 工具，渐进式披露）
- 事件钩子：`.xsh/hooks.json` 声明 pre/post tool-use 钩子（需启用 shell；pre 非零退出可拦截调用）
- 子代理委派：`task` 工具把自包含子任务交给独立上下文的子代理执行并返回报告；可并发多个、或 `background=true` 后台执行后用 `task_status` 轮询
- MCP 客户端：`.xsh/mcp.json` 声明外部 MCP 服务器，其工具以 `mcp__<server>__<tool>` 接入
- 权限策略：`.xsh/permissions.json` 的 `deny_paths`（读写/检索）、`deny_commands`（shell）、`deny_urls`（抓取/搜索）
- 检索增强：`grep` 支持可选正则、忽略大小写与上下文行（默认仍为字面匹配）
- 批量编辑：`multiedit` 对同一文件按序应用多处编辑，全部匹配时一次性原子写入
- 会话导出：`/export [文件]` 把对话写成 Markdown 转录（限制在工作区内）

## 未来计划

- [ ] 更多工具：提供更完善的基础工具集

## 非停机与重启监督

非停机模式（`--non-stop-mode`，或在记录了该任务的会话上 `--resume`）会持续执行任务，
直到收到中断。由于更新 Python 代码需要重启进程，仓库提供独立于 xsh 的监督脚本：

- `.supervisor/restart-supervisor.sh`：加锁、提交候选版本、经 tmux 正常停止旧进程、
  发送 `xsh --resume`、按就绪信号与会话推进校验；失败时保留候选提交、回滚到已知良好
  版本并写入 `RESTART_FAILED.json`。
- `.supervisor/watchdog.sh`：常驻保底，检测到 pane 内长时间没有 xsh 时重新拉起。

重启是否成功以“就绪文件关联到本次启动 + 会话确实推进”为准，而不是仅凭进程存在。

## 安装方式

需要 Python 3.12 或更高版本。在项目根目录安装：

```bash
python -m pip install -e .
```

如果使用 uv，也可以运行 `uv sync` 安装。


## 配置文件

将 `.env.example` 复制为 `.env`，填写模型服务配置：

```dotenv
XSH_BASE_URL=https://your-provider.example/v1
XSH_MODEL=your-model-name
XSH_API_KEY=your-api-key
```

模型服务需提供 OpenAI 兼容的 Chat Completions 接口、流式响应和工具调用。

## 使用方式

> [!IMPORTANT]
> 
> 该项目本质上是个人学习用的玩具项目，可能会有未知问题出现。使用时请注意安全风险，尤其是启用命令执行时。

```bash
xsh              # 多轮交互模式
xsh "1 + 1 = ?"  # 单轮任务模式
```

| 参数                 | 说明                                       |
| -------------------- | ------------------------------------------ |
| `--workspace <目录>` | 指定工作目录，默认为当前目录               |
| `--session <文件>`   | 指定新建会话的 JSONL 文件路径              |
| `--resume [文件或前缀]` | 恢复指定会话（支持文件名前缀），省略时恢复最近修改的会话 |
| `--fork <文件>`      | 复制已有会话为新文件并打开副本（原会话不受影响） |
| `--allow-shell`      | 启用本机命令执行，该功能**无沙箱隔离**     |
| `--verbose`          | 显示系统提示词、推理内容和工具结果         |
| `--non-stop-mode`    | 持续执行同一任务并自动开始下一轮，直到中断 |
| `--max-turns <数>`   | 非停机模式下最多执行的 Turn 数，达到后正常停止 |
| `--max-run-tokens <数>` | 非停机模式的 token 预算，达到后正常停止 |
| `--list-sessions`    | 列出当前工作区已保存的会话（按修改时间倒序）并退出 |
| `--dump-prompt`      | 打印组装后的系统提示词并退出（便于调试）   |
| `--list-tools`       | 列出可用工具及其说明并退出                 |
| `--list-skills`      | 列出工作区技能并退出                       |
| `--doctor`           | 只读环境自检（工作区/配置/可选依赖）并退出 |
| `--print`            | 无终端执行给定 prompt 并打印结果（prompt 可来自参数或 stdin；不启动子代理） |
| `--compact-session [文件]` | 离线压缩会话文件（默认最近会话）并退出 |
| `--ready-file <文件>` | 启动就绪后写入就绪记录（含启动标识/PID/会话），供外部监督脚本验证 |
| `--version`          | 显示版本并退出                             |

### 交互命令

在交互界面中输入以下命令（以 `/` 开头）：

| 命令            | 说明                                             |
| --------------- | ------------------------------------------------ |
| `/list`         | 显示对话历史                                     |
| `/find <文本>`  | 在对话中查找文本                                 |
| `/todos`        | 显示持久化任务清单                               |
| `/memory`       | 显示工作区长期记忆                               |
| `/reload`       | 从磁盘重新读取记忆、技能与权限策略               |
| `/skills`       | 列出可用技能                                     |
| `/tasks`        | 列出后台子任务                                   |
| `/usage`        | 显示累计 token 用量                              |
| `/stats`        | 显示会话概览（轮次/消息/工具/清单）              |
| `/config`       | 显示生效的运行配置                               |
| `/sessions`     | 列出工作区会话                                   |
| `/export [文件]`| 把对话导出为 Markdown 转录（追加清单与记忆小节） |
| `/compact`      | 压缩较早的上下文并保留近期消息                   |
| `/help`         | 显示帮助                                         |
| `/doctor`       | 只读环境自检（工作区/配置/可选依赖）             |
| `/quit`         | 退出 xsh                                         |

### 配置与状态文件

以下文件均位于工作区下、默认被 `.gitignore` 忽略：

| 路径                  | 用途                                             |
| --------------------- | ------------------------------------------------ |
| `.xsh/sessions/*.jsonl` | 会话记录（JSONL 事件流）                       |
| `.xsh/memory.md`      | 长期记忆（`memory` 工具维护，注入系统提示词）     |
| `.xsh/skills/*.md`    | 技能包（`skill` 工具按需加载）                    |
| `.xsh/hooks.json`     | pre/post tool-use 钩子（需启用 shell）           |
| `.xsh/mcp.json`       | 外部 MCP stdio 服务器定义                        |
| `.xsh/permissions.json` | 可选权限策略（`deny_paths` / `deny_commands`）   |
| `.supervisor/`        | 重启监督脚本、日志与状态（`PROGRESS.md` 等）      |

### 环境变量（均可选）

| 变量                     | 说明                                             |
| ------------------------ | ------------------------------------------------ |
| `XSH_BASE_URL` / `XSH_MODEL` / `XSH_API_KEY` | 模型端点、模型名与密钥         |
| `XSH_ALLOW_SHELL`        | 置 1/true 时无需 `--allow-shell` 即启用 shell（注意无沙箱） |
| `XSH_MAX_STEPS`          | 单轮最大 Step 数                                 |
| `XSH_MAX_TURNS`          | 非停机模式最多 Turn 数                           |
| `XSH_MAX_RUN_TOKENS`     | 非停机运行 token 预算                            |
| `XSH_SESSION_COMPACT_MB` | 恢复时超过该大小则离线压缩会话（0 关闭）         |
| `XSH_CONTEXT_WINDOW`     | 模型上下文窗口（自动探测可覆盖）                 |
| `XSH_AUTO_COMPACT` / `XSH_COMPACT_THRESHOLD` / `XSH_COMPACT_RETAIN_RATIO` | 自动压缩开关与阈值 |
| `XSH_REQUEST_TIMEOUT` / `XSH_MAX_RETRIES` | 请求超时与重试次数          |

### 配置文件示例

`.xsh/permissions.json`（可选，拒绝敏感路径读写、危险命令与特定 URL）：

```json
{
  "deny_paths": ["**/.env", "secrets/**"],
  "deny_commands": ["rm -rf *", "git push*"],
  "deny_urls": ["https://tracker.example/*"]
}
```

`.xsh/hooks.json`（可选，需启用 shell；`pre_tool` 非零退出会拦截该次工具调用）：

```json
{"pre_tool": "echo checking", "post_tool": "./scripts/format.sh"}
```

`.xsh/mcp.json`（可选，接入外部 MCP stdio 服务器）：

```json
{"servers": {"demo": {"command": "npx", "args": ["-y", "some-mcp-server"]}}}
```

技能：在 `.xsh/skills/<name>.md` 写入 Markdown 指令包（首行作为摘要），模型可用
`skill` 工具按需加载；记忆：`memory` 工具写入 `.xsh/memory.md`，`/reload` 可重读磁盘。

