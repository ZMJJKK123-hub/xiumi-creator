"""秀米页面 DOM 踩点脚本：dump 元素树 + 截图，用于确认/更新插件选择器。

用法: python main.py recon   （或 python scripts/recon.py）
产出: recon/<名字>_outline.json 与 recon/<名字>.png
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdp.browser import EdgeBrowser
from core.config import load_config

RECON_DIR = None  # 延迟初始化：见 run_recon（依赖 XIUMI_HOME）


def _recon_dir() -> Path:
    global RECON_DIR
    if RECON_DIR is None:
        from core.config import XIUMI_HOME

        RECON_DIR = XIUMI_HOME / "recon"
    return RECON_DIR

TARGETS = [
    ("home", "https://xiumi.us/"),
    ("auth", "https://xiumi.us/auth"),
    # 登录后可手动加上编辑器地址，例如:
    # ("editor", "https://xiumi.us/studio/v5"),
]


async def recon_page(browser: EdgeBrowser, tab, name: str) -> None:
    print(f"\n===== {name} =====")
    await asyncio.sleep(2.0)
    tree = await tab.agent("outline")
    out_json = _recon_dir() / f"{name}_outline.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(tree, ensure_ascii=False, indent=1), encoding="utf-8")
    shot = _recon_dir() / f"{name}.png"
    await tab.screenshot(path=shot)
    print(f"url: {tree['url']}")
    print(f"title: {tree['title']}")
    print(f"refs: {tree['refs']}")
    print(f"outline -> {out_json}")
    print(f"截图 -> {shot}")

    # 额外收集：登录页常见输入元素
    if name == "auth":
        inputs = await tab.agent("find", "input", 20)
        print(f"\ninput 元素 {len(inputs)} 个:")
        for d in inputs:
            print("  ", json.dumps(d, ensure_ascii=False))
        qrs = await tab.agent(
            "find",
            "img[src*='qr'], .qrcode img, iframe, canvas",
            20,
        )
        print(f"\n疑似二维码/iframe 元素 {len(qrs)} 个:")
        for d in qrs:
            print("  ", json.dumps(d, ensure_ascii=False))


async def run_recon() -> None:
    _recon_dir().mkdir(parents=True, exist_ok=True)
    config = load_config()
    browser = EdgeBrowser(config)
    await browser.ensure_started()
    await browser.connect()
    tab = await browser.get_or_create_tab("xiumi.us", "https://xiumi.us/")
    try:
        for name, url in TARGETS:
            await tab.navigate(url, settle=2.0)
            await recon_page(browser, tab, name)
        print("\n完成。请查看 recon/ 目录；把确认的选择器更新到 plugins/*/selectors.json。")
        print("提示: 在浏览器里手动登录后，重跑本脚本并把编辑器 URL 加到 TARGETS 可踩编辑器。")
    finally:
        await browser.shutdown()


if __name__ == "__main__":
    start = time.time()
    asyncio.run(run_recon())
    print(f"用时 {time.time()-start:.1f}s")
