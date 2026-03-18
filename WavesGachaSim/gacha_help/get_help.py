"""鸣潮模拟抽卡 - 帮助图生成"""

import json
from typing import Dict
from pathlib import Path

from PIL import Image

from gsuid_core.help.model import PluginHelp
from gsuid_core.help.draw_new_plugin_help import get_new_help

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "help.json"

# 复用 XutheringWavesUID 的素材（如果存在），否则用默认
XWUID_HELP_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "XutheringWavesUID"
    / "XutheringWavesUID"
    / "wutheringwaves_help"
)
TEXT_PATH = XWUID_HELP_PATH / "texture2d"
ICON_PATH = XWUID_HELP_PATH / "icon_path"


def get_help_data() -> Dict[str, PluginHelp]:
    """读取 help.json"""
    with open(HELP_DATA, "r", encoding="utf-8") as f:
        return json.load(f)


async def get_help(pm: int = 6):
    """生成帮助图"""
    kwargs = dict(
        plugin_name="WavesGachaSim",
        plugin_info={"v0.1.0": ""},
        plugin_help=get_help_data(),
        plugin_prefix="",  # help.json 中命令已含前缀
        help_mode="dark",
        banner_sub_text="试试你的运气吧！",
        enable_cache=True,
        pm=pm,
    )

    # 插件 ICON
    if ICON.exists():
        kwargs["plugin_icon"] = Image.open(ICON).convert("RGBA")

    # 复用 XutheringWavesUID 的素材（可选）
    if TEXT_PATH.exists():
        banner_bg = TEXT_PATH / "banner_bg.jpg"
        bg = TEXT_PATH / "bg.jpg"
        cag_bg = TEXT_PATH / "cag_bg.png"
        item_bg = TEXT_PATH / "item.png"

        if banner_bg.exists():
            kwargs["banner_bg"] = Image.open(banner_bg).convert("RGBA")
        if bg.exists():
            kwargs["help_bg"] = Image.open(bg).convert("RGBA")
        if cag_bg.exists():
            kwargs["cag_bg"] = Image.open(cag_bg).convert("RGBA")
        if item_bg.exists():
            kwargs["item_bg"] = Image.open(item_bg).convert("RGBA")

    if ICON_PATH.exists():
        kwargs["icon_path"] = ICON_PATH

    return await get_new_help(**kwargs)
