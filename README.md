# xsh - extremely small harness

xsh 是一个模仿 [dsh](https://github.com/deepseek-ai/deepseek-harness) 的极简单智能体 harness，实现了智能体 Turn + Step 循环等最核心的功能。它也是我学习 dsh 源码后的练手项目，因此代码中已经提供了较详细的注释，方便学习和理解。

![demo.gif](demo.gif)

~~既然 dsh 叫 大烧货，那么 xsh 当然能叫 小烧货 吧~~

## 当前功能

- 智能体循环：支持多轮对话与多步工具执行
- 工具调用：支持文件操作与命令执行
- 项目指令：系统提示词与 AGENTS.md 指导任务执行
- 上下文压缩：压缩历史消息以支持长任务
- 会话恢复：持久化会话并支持恢复上下文
- 中断处理：修复未完成调用并保留执行记录

## 未来计划

- [ ] 更多工具：提供更完善的基础工具集

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

| 参数                 | 说明                                   |
| -------------------- | -------------------------------------- |
| `--workspace <目录>` | 指定工作目录，默认为当前目录           |
| `--session <文件>`   | 指定新建会话的 JSONL 文件路径          |
| `--resume <文件>`    | 恢复已有会话，与 `--session` 互斥      |
| `--allow-shell`      | 启用本机命令执行，该功能**无沙箱隔离** |
| `--verbose`          | 显示系统提示词、推理内容和工具结果     |

