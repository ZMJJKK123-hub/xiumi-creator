"""OpenAI 兼容 LLM 客户端（支持智谱/DeepSeek/Kimi/OpenAI 等）。"""
from __future__ import annotations

import asyncio

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from core.config import Config


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "EMPTY",
            timeout=180.0,
            max_retries=0,
        )

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """一轮对话。返回标准化消息 dict：{role, content, tool_calls?}。"""
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                kwargs: dict = {"model": self.config.model, "messages": messages}
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                resp = await self.client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message
                d: dict = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    d["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ]
                return d
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_err = e
                await asyncio.sleep(2**attempt)
        raise RuntimeError(f"LLM 请求失败（已重试 3 次）: {last_err}")
