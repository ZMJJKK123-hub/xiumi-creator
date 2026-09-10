"""快捷键动作：从 App 薄壳拆出的键位行为集合。

Rule2 §3：Mixin 单一职责，app.py 只保留组装；宿主需提供
transcript/_busy/_worker/_set_busy/open_help/_welcome_model/_welcome_cwd。
"""
from __future__ import annotations



class ShortcutActions:
    """全局快捷键动作集合。

    类职责：实现 App BINDINGS 指向的全部 action_* 方法。
    类变量：无。
    生命周期：随宿主 App 存在；每个方法对应一个键位，见 App.BINDINGS。
    """

    def action_interrupt(self) -> None:
        """esc：取消进行中的任务 worker。"""
        if self._busy and self._worker is not None:
            self._worker.cancel()
            self._set_busy(False)
            self.transcript().write_system("⏹ 已中断（esc）")

    def action_help(self) -> None:
        """?：打开帮助浮层。"""
        self.open_help()

    def action_clear_logs(self) -> None:
        """ctrl+l：清屏并重绘欢迎卡。"""
        t = self.transcript()
        t.clear()
        t.write_welcome(self._welcome_model(), self._welcome_cwd())

    def action_suggest_next(self) -> None:
        """Tab：候选打开时下一个候选，否则正常切换焦点。"""
        if len(self.screen_stack) == 1 and self.suggest.is_open:
            self.suggest.step(1)
        else:
            self.screen.focus_next()

    def action_suggest_prev(self) -> None:
        """Shift+Tab：候选打开时上一个候选，否则正常切换焦点。"""
        if len(self.screen_stack) == 1 and self.suggest.is_open:
            self.suggest.step(-1)
        else:
            self.screen.focus_previous()

    def action_scroll_transcript_up(self) -> None:
        """PgUp：流水上翻一页。"""
        try:
            self.transcript().scroll_page_up()
        except Exception as exc:  # noqa: BLE001 翻页失败仅记调试
            self.logger.debug("scroll_up 失败: %s", exc)

    def action_scroll_transcript_down(self) -> None:
        """PgDn：流水下翻一页。"""
        try:
            self.transcript().scroll_page_down()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("scroll_down 失败: %s", exc)


class LLMConfigActions:
    """LLM 配置应用集合（Mixin）。

    类职责：模型/Key/地址变更后即时刷新 LLM 客户端与状态栏。
    宿主需提供：config、agent、ctx、registry、bus、set_status、logger。
    """

    def apply_model(self, name: str) -> None:
        """应用模型名变更。Args: name 模型名。Calls: _refresh_agent。"""
        self.config.model = name
        self._refresh_agent()

    def apply_llm_config(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """应用 Key/地址变更（None 项不变）。Args: api_key/base_url 新值。"""
        if api_key is not None:
            self.config.api_key = api_key
        if base_url is not None:
            self.config.base_url = base_url
        self._refresh_agent()

    def _refresh_agent(self) -> None:
        """按当前配置刷新：就绪重建 LLM 客户端，未就绪提示缺项命令。"""
        from core.llm import LLMClient  # 局部导入：避免模块级循环

        if self.agent is not None:
            self.agent.llm = LLMClient(self.config)
        elif self.config.llm_ready and self.ctx.tab:
            from core.agent import Agent  # 局部导入

            self.agent = Agent(self.ctx, self.registry, LLMClient(self.config), self.bus)
        if self.config.llm_ready:
            self.set_status(f"{self.config.model} · {len(self.registry.names())} tools")
            return
        missing = [c for c, ok in (
            ("/key", self.config.api_key), ("/url", self.config.base_url), ("/model", self.config.model),
        ) if not ok]
        self.set_status("未配置" + " ".join(missing) if missing else "就绪")
