"""model.py - 实现调用 OpenAI 库的相关模型请求逻辑"""

from collections.abc import Callable
from typing import Any, Protocol

from openai import OpenAI

from xsh.constants import (
    MODEL_DEFAULT_MAX_TOKENS,
)
from xsh.messages import Message, ModelResponse, ToolCall


class Model(Protocol):
    """模型接口。和基类继承写法类似，但无需显式继承，主要用于类型检查"""

    def build_request(self, messages: list[Message], tools: list[dict]) -> dict:
        """由项目内格式的消息和工具列表构建模型请求体"""
        pass

    def complete(self, request: dict, on_text: Callable[[str], None] | None = None, on_reasoning: Callable[[str], None] | None = None) -> ModelResponse:
        """输入 build_request 构建的请求体，返回符合项目 ModelResponse 格式的响应。on_text 回调函数用于流式输出文本内容"""
        pass


class OpenAIModel:
    """OpenAI 模型实现类"""

    def __init__(self, client: OpenAI, model: str, max_tokens: int = MODEL_DEFAULT_MAX_TOKENS):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def build_request(self, messages: list[Message], tools: list[dict]) -> dict:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_wire() for message in messages],
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = tools
        return request

    def complete(self, request: dict, on_text: Callable[[str], None] | None = None, on_reasoning: Callable[[str], None] | None = None) -> ModelResponse:
        content: list[str] = []                # 正常文本结果
        refusals: list[str] = []               # 拒绝文本结果
        reasoning: list[str] = []              # 推理文本结果
        calls: dict[int, dict[str, str]] = {}  # 工具调用结果
        finish_reason = None                   # 结束原因
        usage = {}
        # 注意：OpenAI 库自带请求重试
        with self.client.chat.completions.create(**request) as stream:
            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                if not chunk.choices:  # 部分服务商可能返回空 choices，直接忽略。
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # 推理文本先于同一块中的正文显示。
                if value := getattr(delta, "reasoning_content", None):
                    reasoning.append(value)
                    if on_reasoning:
                        on_reasoning(value)

                # 正常文本块
                if delta.content:
                    content.append(delta.content)
                    if on_text:
                        on_text(delta.content)

                # 拒绝文本块
                if delta.refusal:
                    refusals.append(delta.refusal)
                    if on_text:
                        on_text(delta.refusal)

                # 工具调用块，可能为 None
                for part in delta.tool_calls or []:
                    if part.type not in {None, "function"}:
                        raise ValueError("Only function tool calls are supported")

                    # 按 index 合并拼接各字段
                    call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                    if part.id:
                        call["id"] += part.id
                    if part.function:
                        call["name"] += part.function.name or ""
                        call["arguments"] += part.function.arguments or ""

                # 保存结束原因
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        # 没有结束原因，说明异常终止
        if finish_reason is None:
            raise ValueError("Provider stream ended without a finish reason")

        # 将工具调用转为 ToolCall 对象
        tool_calls = []
        if finish_reason in {"stop", "tool_calls"}:  # 只在正常情况下处理工具调用，防止不完整的调用数据
            for index in sorted(calls):
                call = calls[index]
                tool_call = ToolCall(**call)
                tool_calls.append(tool_call)

        # 结束原因是 tool_calls，但实际没有调用。何意味？异常！
        if finish_reason == "tool_calls" and not tool_calls:
            raise ValueError("Provider finished with tool_calls but returned no calls")

        # 组装 ModelResponse 对象
        return ModelResponse(
            message=Message(
                role="assistant",
                content="".join(content) or "".join(refusals) or None,
                reasoning_content="".join(reasoning) or None,
                tool_calls=tool_calls,
            ),
            finish_reason=finish_reason,
            usage=usage,
        )
