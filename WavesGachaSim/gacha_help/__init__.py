"""鸣潮模拟抽卡 - 帮助命令注册"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.help.utils import register_help

from .get_help import ICON, get_help

try:
    from gsuid_core.sv import get_plugin_available_prefix
    PREFIX = get_plugin_available_prefix("XutheringWavesUID")
except Exception:
    PREFIX = "ww"

sv_gacha_help = SV(f"{PREFIX}模拟抽卡帮助")


@sv_gacha_help.on_fullmatch(("模拟抽卡帮助",), block=True)
async def send_gacha_help(bot: Bot, ev: Event):
    """发送帮助图"""
    im = await get_help(ev.user_pm)
    await bot.send(im)


# 注册到全局帮助列表
if ICON.exists():
    from PIL import Image
    register_help(
        "WavesGachaSim",
        f"{PREFIX}模拟抽卡帮助",
        Image.open(ICON),
    )
