"""xiumi_editor 插件：秀米排版编辑器的业务工具。

新建草稿 / 设标题 / 插入排版 HTML / 插入本地图片 / 保存 / 预览截图 / 复制到公众号。
选择器见同目录 selectors.json（recon.py 踩点后更新）。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from core.registry import AppContext, Plugin, Tool

HERE = Path(__file__).parent


def _selectors() -> dict:
    return json.loads((HERE / "selectors.json").read_text(encoding="utf-8"))


def _shot_path(ctx: AppContext, name: str | None) -> Path:
    path = Path(name) if name else Path(time.strftime("preview_%H%M%S.png"))
    if not path.is_absolute():
        path = ctx.config.screenshots_dir / path
    return path.with_suffix(".png")


async def _new_draft(ctx: AppContext, args: dict) -> str:
    sel = _selectors()
    tab = ctx.require_tab()
    title = str(args.get("title", "未命名图文")).strip()

    url = await tab.current_url()
    if sel["editor_new_url"] not in url:
        await tab.navigate(sel["editor_new_url"])
    ok = await tab.wait_selector('[contenteditable="true"]', timeout=15)
    if not ok:
        return (
            "ERROR: 编辑器页面未出现可编辑区域。可能原因：未登录 / 编辑器 URL 变化。"
            "建议先用 xiumi_login_check 检查登录，再用 browser_dom_outline 观察当前页。"
        )
    info = await tab.agent("editorInfo")
    ctx.state["draft_title"] = title
    ctx.state["blocks"] = 0
    ctx.state["images"] = 0
    await _set_title_inner(ctx, title)
    return f"已进入编辑器（编辑区 ref={info['ref']}，当前块数 {info['blocks']}）。标题已设为「{title}」"


async def _set_title_inner(ctx: AppContext, title: str) -> None:
    """按 选择器 → placeholder 文本 两条路径找标题输入框。"""
    tab = ctx.require_tab()
    sel = _selectors()
    found = await tab.agent("find", sel["title_input"], 3)
    if not found:
        found = await tab.agent("find", f"input[placeholder*='{sel['title_text_hint']}']", 3)
    if not found:
        raise RuntimeError("找不到标题输入框（选择器可能过期，可用 outline 观察）")
    await tab.agent("type", found[0]["ref"], title)


async def _set_title(ctx: AppContext, args: dict) -> str:
    title = str(args["title"]).strip()
    await _set_title_inner(ctx, title)
    ctx.state["draft_title"] = title
    return f"标题已设为「{title}」"


async def _insert_html(ctx: AppContext, args: dict) -> str:
    html = str(args["html"]).strip()
    if not html.startswith("<"):
        return "ERROR: html 参数必须是 HTML 片段（以 < 开头）"
    tab = ctx.require_tab()
    res = await tab.agent("editorInsert", html)
    ctx.state["blocks"] = ctx.state.get("blocks", 0) + 1
    await asyncio.sleep(0.35)
    return f"已插入第 {ctx.state['blocks']} 个内容块（方式: {res['mode']}）"


async def _insert_image(ctx: AppContext, args: dict) -> str:
    """上传本地图片：点击图片入口 → CDP 塞文件 → 触发 change。"""
    sel = _selectors()
    tab = ctx.require_tab()
    path = str(args["path"])
    if not Path(path).exists():
        # 相对路径按项目根再试一次
        alt = Path.cwd() / path
        if alt.exists():
            path = str(alt.resolve())
        else:
            return f"ERROR: 图片不存在: {path}"

    # 1) 确保 file input 存在：没有就先点开「图片」入口
    has_input = await tab.evaluate(f"!!document.querySelector({json.dumps(sel['file_input'])})")
    if not has_input:
        btns = await tab.agent("findByText", sel["upload_button_text"], "span, a, button, li, div", 5)
        if not btns:
            return "ERROR: 找不到图片上传入口，也找不到 file input。请用 outline 观察工具栏后用 exec_js 处理"
        await tab.agent("click", btns[0]["ref"])
        await asyncio.sleep(1.0)
        has_input = await tab.evaluate(f"!!document.querySelector({json.dumps(sel['file_input'])})")
        if not has_input:
            return "ERROR: 点击图片入口后仍未出现 file input，可能弹出了独立的图片面板，请 outline 观察"

    # 2) CDP 注入文件（纯 JS 做不到）
    try:
        await tab.set_files(sel["file_input"], [path])
    except Exception as e:
        return f"ERROR: 文件注入失败: {e}"

    await asyncio.sleep(2.5)  # 等上传
    ctx.state["images"] = ctx.state.get("images", 0) + 1
    return (
        f"已通过图库上传图片 {path}（第 {ctx.state['images']} 张）。"
        "注意：部分版本上传后图片停留在图库面板，需要点击图库中的图片才会插入正文；"
        "可用 browser_dom_outline 观察，若图库面板里出现了刚上传的图片请点击它。"
    )


async def _save(ctx: AppContext, args: dict) -> str:
    sel = _selectors()
    tab = ctx.require_tab()
    btns = await tab.agent("findByText", sel["save_text"], "button, a, span, div[role='button']", 5)
    if not btns:
        return "ERROR: 找不到保存按钮。请 outline 观察工具栏，注意秀米可能有自动保存"
    await tab.agent("click", btns[0]["ref"])
    await asyncio.sleep(1.5)
    return "已点击保存（秀米通常有自动保存，若弹窗提示请 outline 确认）"


async def _preview(ctx: AppContext, args: dict) -> str:
    sel = _selectors()
    tab = ctx.require_tab()
    path = _shot_path(ctx, args.get("filename"))
    selector = sel.get("canvas_selector") or None
    try:
        out = await tab.screenshot(path=path, selector=selector)
    except Exception:
        out = await tab.screenshot(path=path)
    await ctx.events.emit("screenshot", path=str(out))
    return f"编辑器截图已保存: {out}"


async def _copy_for_wechat(ctx: AppContext, args: dict) -> str:
    sel = _selectors()
    tab = ctx.require_tab()
    for text in sel["copy_texts"]:
        btns = await tab.agent("findByText", text, "button, a, span, div[role='button']", 3)
        if btns:
            await tab.agent("click", btns[0]["ref"])
            await asyncio.sleep(1.0)
            return f"已点击「{text}」。内容已进剪贴板，可到公众号后台编辑器里直接粘贴"
    return "ERROR: 找不到复制按钮，请 outline 观察"


class XiumiEditorPlugin(Plugin):
    name = "xiumi_editor"
    description = "秀米排版编辑器：新建图文、设标题、插入 HTML 块、上传插图、保存、预览、复制到公众号"

    def tools(self, ctx: AppContext) -> list[Tool]:
        return [
            Tool(
                name="xiumi_new_draft",
                description="新建一篇图文草稿并设置标题。会在编辑器就绪后进入正文编辑状态。",
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string", "description": "文章标题"}},
                    "required": ["title"],
                },
                handler=_new_draft,
            ),
            Tool(
                name="xiumi_set_title",
                description="修改当前图文的标题",
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
                handler=_set_title,
            ),
            Tool(
                name="xiumi_insert_html",
                description=(
                    "向正文末尾插入一段微信排版 HTML 块（必须遵守系统提示词的排版规范：内联样式、"
                    "section 嵌套、无 div/script）。每次调用插入一个块级片段。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"html": {"type": "string", "description": "HTML 片段，以 < 开头"}},
                    "required": ["html"],
                },
                handler=_insert_html,
            ),
            Tool(
                name="xiumi_insert_image",
                description="上传本地图片到秀米图库并尝试插入（对应任务里的 [img:路径] 标记）",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "本地图片绝对或相对路径"}},
                    "required": ["path"],
                },
                handler=_insert_image,
            ),
            Tool(
                name="xiumi_save",
                description="保存当前图文草稿",
                parameters={"type": "object", "properties": {}},
                handler=_save,
            ),
            Tool(
                name="xiumi_preview",
                description="截图当前编辑器画面，用于检查排版效果",
                parameters={
                    "type": "object",
                    "properties": {"filename": {"type": "string", "description": "截图文件名（可省略）"}},
                },
                handler=_preview,
            ),
            Tool(
                name="xiumi_copy_for_wechat",
                description="点击「复制到公众号」，内容进剪贴板后可在公众号后台粘贴（仅在用户明确要求时使用）",
                parameters={"type": "object", "properties": {}},
                handler=_copy_for_wechat,
            ),
        ]
