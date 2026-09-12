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
        """esc：取消任务 worker；无 worker 的忙碌态（意外残留）也解除。"""
        if not self._busy:
            return
        if self._worker is not None:
            self._worker.cancel()
        self._set_busy(False)
        self.transcript().write_system("⏹ 已中断（esc）")

    def action_clear_logs(self) -> None:
        """ctrl+l：清空流水区并刷新欢迎卡。"""
        self.transcript().clear()
        self.refresh_welcome()

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
        """按当前配置刷新 Agent：已有则换 LLM 客户端，就绪且浏览器在位则新建。"""
        from core.llm import LLMClient  # 局部导入：避免模块级循环

        if self.agent is not None:
            self.agent.llm = LLMClient(self.config)
        elif self.config.llm_ready and self.ctx.tab:
            from core.agent import Agent  # 局部导入

            self.agent = Agent(self.ctx, self.registry, LLMClient(self.config), self.bus)
