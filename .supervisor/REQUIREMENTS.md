#xsh 需求与路线图（由用户留言派生）
#
# 来源：用户在 `.supervisor/PROGRESS.md` 留下的指令——
#   "请尝试更多更大型的功能，而不是全部都是小修补，可以尝试使用网络工具检索当前的
#    Agent 框架都有些什么功能。请将该需求写入你保存需求的文档。"（该留言已按要求删除）
#
# 调研对象（外部、仅作参考）：Claude Code（子代理 / Skills / hooks / 会话记忆 / 路径作用域规则）、
# OpenHands（microagents / 事件流压缩）、Cursor/Aider（rules、repo map）、
# 以及 Agent SDK 的长期记忆笔记模式。

## 大功能候选（按价值/契合度排序）
1. **长期记忆（memory）** ✅ 本轮实现
   - 工作区级持久笔记（`.xsh/memory.md`），跨会话保留；注入系统提示词；
     工具支持 add/replace/remove；`/memory` 查看。对应 Claude Code 的会话记忆与
     OpenAI cookbook 的 "long-term memory notes"。
2. **Hooks（事件钩子）** ✅ 本轮实现
   - `.xsh/hooks.json` 的 pre/post tool-use 钩子；pre 非零退出可拦截调用。
3. **Skills / 可复用指令包** ✅ 本轮实现
   - `.xsh/skills/*.md` 的可按需加载技能（渐进式披露）；`skill` 工具 + 提示词索引。
4. **后台任务（background subtasks）** ✅ 本轮实现
   - `task(background=true)` 返回句柄，`task_status` 工具轮询/列出。
5. **成本/预算护栏** ✅ 本轮实现
   - `--max-run-tokens` / `XSH_MAX_RUN_TOKENS`：单次（非停机）运行的 token 上限。
6. **MCP 客户端** ✅ 本轮实现
   - `.xsh/mcp.json` 声明 stdio 服务器；行分隔 JSON-RPC 握手后把其工具接入本地工具集
     （`mcp__<server>__<tool>`），失败优雅降级。

## 设计约束
- 不改动既有稳定行为；新功能默认安全、可配置、可测试。
- 记忆文件位于 `.xsh/` 下（gitignored），避免污染用户提交。
- 每轮仍遵循 分析 → 实现 → 测试 → 提交 → 重启 → 验证 → 记录 的闭环。
