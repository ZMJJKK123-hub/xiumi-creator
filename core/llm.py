"""OpenAI 兼容 LLM 客户端（支持智谱/DeepSeek/Kimi/opencode 网关等）。"""
from __future__ import annotations

import asyncio  # 重试退避
import uuid  # 网关会话标识

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from core.config import Config

# 进程级网关会话 ID：opencode Zen 网关要求 x-opencode-session 路由请求
_SESSION_ID = f"xiumi-agent-{uuid.uuid4().hex[:12]}"


class LLMClient:
    """OpenAI 兼容客户端。

    类职责：统一 chat 入口，标准化消息结构，网络类错误三次退避重试。
    属性：config 配置引用；client 底层 SDK 客户端。
    生命周期：随配置构造（/model 保存后重建实例）。
    """

    def __init__(self, config: Config):
        """按配置构造客户端；opencode 网关附加会话头。

        Args: config 含 base_url/api_key/model。
        """
        self.config = config
        headers: dict[str, str] = {}
        if "opencode" in config.base_url:
            headers["x-opencode-session"] = _SESSION_ID
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "EMPTY",
            timeout=180.0,
            max_retries=0,
            default_headers=headers,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_reasoning: "callable | None" = None,
        on_content: "callable | None" = None,
    ) -> dict:
        """流式对话：思考/正文增量经回调实时吐出，返回聚合后的消息 dict。

        Args: messages 对话历史; tools 工具声明; on_reasoning 思考增量回调;
            on_content 正文增量回调。Returns: {role, content, reasoning_content?, tool_calls?}。
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                kwargs: dict = {"model": self.config.model, "messages": messages, "stream": True}
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                stream = await self.client.chat.completions.create(**kwargs)
                return await self._consume_stream(stream, on_reasoning, on_content)
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_err = e
                await asyncio.sleep(2**attempt)
        raise RuntimeError(f"LLM 请求失败（已重试 3 次）: {last_err}")

    async def _consume_stream(self, stream, on_reasoning, on_content) -> dict:
        """消费流：聚合思考/正文/工具调用分片，思考与正文增量实时回调。

        Args: stream SDK 流对象; on_reasoning/on_content 增量回调。
        Returns: 标准化消息 dict。
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict] = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "reasoning_content", None)
            if piece:
                reasoning_parts.append(piece)
                if on_reasoning:
                    on_reasoning(piece)
            if delta.content:
                content_parts.append(delta.content)
                if on_content:
                    on_content(delta.content)
            for tc in delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["args"] += tc.function.arguments
        d: dict = {"role": "assistant", "content": "".join(content_parts)}
        if reasoning_parts:
            d["reasoning_content"] = "".join(reasoning_parts)
        if calls:
            d["tool_calls"] = [
                {"id": s["id"], "type": "function", "function": {"name": s["name"], "arguments": s["args"]}}
                for _, s in sorted(calls.items())
            ]
        return d
