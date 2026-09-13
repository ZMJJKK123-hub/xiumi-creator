"""快捷键动作：从 App 薄壳拆出的键位行为集合。

Rule2 §3：Mixin 单一职责，app.py 只保留组装；宿主需提供
transcript/_busy/_worker/_set_busy/open_help/refresh_welcome/query_one。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）



class ShortcutActions:
    """全局快捷键动作集合。

    类职责：实现 App BINDINGS 指向的全部 action_* 方法。
    类变量：无。
    生命周期：随宿主 App 存在；每个方法对应一个键位，见 App.BINDINGS。
    """

    def action_interrupt(self) -> None:
        """esc：取消任务 worker；无 worker 的忙碌态（意外残留）也解除。

        Globals Used: None。Calls: worker.cancel / _set_busy / transcript。
        Args: None。Returns: None。
        """
        if not self._busy:
            return
        if self._worker is not None:
            self._worker.cancel()
        self._set_busy(False)
        self.transcript().write_system("⏹ 已中断（esc）")

    def action_clear_logs(self) -> None:
        """ctrl+l：清空流水区并刷新欢迎卡。Calls: transcript.clear / refresh_welcome。Args: None。Returns: None。"""
        self.transcript().clear()
        self.refresh_welcome()

    def action_suggest_next(self) -> None:
        """Tab：候选打开时下一个候选，否则正常切换焦点。Calls: suggest.step / focus_next。Args: None。Returns: None。"""
        if len(self.screen_stack) == 1 and self.suggest.is_open:
            self.suggest.step(1)
        else:
            self.screen.focus_next()

    def action_suggest_prev(self) -> None:
        """Shift+Tab：候选打开时上一个候选，否则正常切换焦点。Calls: suggest.step / focus_previous。Args: None。Returns: None。"""
        if len(self.screen_stack) == 1 and self.suggest.is_open:
            self.suggest.step(-1)
        else:
            self.screen.focus_previous()

    def action_toggle_thinking(self) -> None:
        """ctrl+o：思考过程收起 ⇄ 展开（10 行独立滚动视窗）。Calls: _think.toggle。Args: None。Returns: None。"""
        if len(self.screen_stack) == 1 and self._think is not None:
            self._think.toggle()

    def action_scroll_transcript_up(self) -> None:
        """PgUp：流水上翻一页。Calls: transcript.scroll_page_up。Args: None。Returns: None。"""
        """PgUp：流水上翻一页。"""
        try:
            self.transcript().scroll_page_up()
        except Exception as exc:  # noqa: BLE001 翻页失败仅记调试
            self.logger.debug("scroll_up 失败: %s", exc)

    def action_scroll_transcript_down(self) -> None:
        """PgDn：流水下翻一页。Calls: transcript.scroll_page_down。Args: None。Returns: None。"""
        """PgDn：流水下翻一页。"""
        try:
            self.transcript().scroll_page_down()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("scroll_down 失败: %s", exc)


class LLMConfigActions:
    """LLM 配置动作混入：/model 保存后的即席生效。

    类职责：应用模型/密钥/地址变更并重建 Agent。
    属性：无实例状态（全部读宿主）。
    生命周期：宿主 App 继承；配置屏保存时调用。
    """
    """LLM 配置应用集合（Mixin）。

    类职责：模型/Key/地址变更后即时刷新 LLM 客户端与状态栏。
    """

    def apply_model(self, name: str) -> None:
        """应用模型名变更。Globals Used: None。Calls: _refresh_agent。Args: name 模型名。Returns: None。"""
        self.config.model = name
        self._refresh_agent()

    def apply_llm_config(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """应用 Key/地址变更（None 项不变）。Globals Used: None。Calls: _refresh_agent。
        Args: api_key/base_url 新值。Returns: None。"""
        if api_key is not None:
            self.config.api_key = api_key
        if base_url is not None:
            self.config.base_url = base_url
        self._refresh_agent()

    def _refresh_agent(self) -> None:
        """按当前配置刷新 Agent：已有则换 LLM 客户端，就绪且浏览器在位则新建。
        Args: None。Returns: None。"""
        from core.llm import LLMClient  # 局部导入：避免模块级循环

        if self.agent is not None:
            self.agent.llm = LLMClient(self.config)
        elif self.config.llm_ready and self.ctx.tab:
            from core.agent import Agent  # 局部导入

            self.agent = Agent(self.ctx, self.registry, LLMClient(self.config), self.bus)

    def open_help(self) -> None:
        """打开快捷键帮助浮层。Calls: push_screen。Args: None。Returns: None。"""
        from tui.screens import HelpScreen  # 局部导入：避免循环依赖

        self.push_screen(HelpScreen())

    def _welcome_model(self) -> str:
        """模型显示文案：未配好时提示未配置。Args: None。Returns: str。"""
        return self.config.model if self.config.llm_ready else "未配置"

    async def quick_shot(self) -> None:
        """手动截图当前页面到 screenshots 目录（/shot 的 worker 协程）。
        Globals Used: None。Calls: tab.screenshot / transcript。Args: None。Returns: None。
        """
        import time  # 截图文件命名

        try:
            path = self.config.screenshots_dir / f'manual_{time.strftime("%H%M%S")}.png'
            await self.ctx.tab.screenshot(path=path)
            self.transcript().write_tool_note(f"截图: {path}")
        except Exception as exc:  # noqa: BLE001 截图失败转为用户提示
            self._chat("system", f"截图失败: {exc}")
