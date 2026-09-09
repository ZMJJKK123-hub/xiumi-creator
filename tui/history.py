"""输入历史：回溯已提交命令 + 未提交草稿保护。

Rule2 §1 独立状态小类，纯逻辑无 UI 依赖。
"""
from __future__ import annotations


class InputHistory:
    """终端输入历史管理。

    职责：记录用户提交过的输入；↑ 向旧翻页、↓ 向新翻页并回到底部恢复草稿。
    属性：items 已提交输入列表；_index 当前浏览位置（None=未在浏览态）；
    _draft 进入浏览态前的输入草稿。
    生命周期：App 构造时创建，随 App 回收。
    """

    def __init__(self) -> None:
        self.items: list[str] = []
        self._index: int | None = None
        self._draft: str = ""

    def record(self, value: str) -> None:
        """记录一次提交并退出浏览态。

        Args: value 提交的原始输入。Returns: None。Globals Used: None。
        """
        self.items.append(value)
        self._index = None

    def prev(self, current: str) -> str:
        """↑：向更早翻一条；首次进入浏览态时保护 current 为草稿。

        Args: current 当前输入框内容。Returns: 应回填的输入框内容（钳制在最旧一条）。
        """
        if not self.items:
            return current
        if self._index is None:
            self._draft = current
            self._index = len(self.items) - 1
        elif self._index > 0:
            self._index -= 1
        return self.items[self._index]

    def next(self) -> str:
        """↓：向更新翻一条；翻到底部后返回受保护的草稿。

        Args: None。Returns: 应回填的输入框内容；未在浏览态时原样返回草稿。
        """
        if self._index is None:
            return self._draft
        if self._index < len(self.items) - 1:
            self._index += 1
            return self.items[self._index]
        self._index = None
        return self._draft
