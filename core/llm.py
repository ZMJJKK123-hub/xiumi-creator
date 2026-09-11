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
