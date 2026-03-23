"""鸣潮抽卡模拟器 - 配置"""

from typing import Dict

from gsuid_core.utils.plugins_config.gs_config import StringConfig
from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsIntConfig,
    GsBoolConfig,
    GsStrConfig,
)
from gsuid_core.data_store import get_res_path

# 插件专属配置目录
GACHA_SIM_MAIN_PATH = get_res_path() / "WavesGachaSim"
GACHA_SIM_MAIN_PATH.mkdir(parents=True, exist_ok=True)
GACHA_SIM_CONFIG_PATH = GACHA_SIM_MAIN_PATH / "gacha_sim_config.json"

GACHA_SIM_CONFIG_DEFAULT: Dict[str, GSC] = {
    "GachaSimDailyLimit": GsIntConfig(
        title="每日抽卡次数上限",
        desc="每个用户每天每种卡池类型的模拟抽卡次数上限，0为无限制",
        data=300,
        max_value=9999,
    ),
    "GachaSimEnableBailian": GsBoolConfig(
        title="百连功能开关",
        desc="⚠️注意：此配置会增加渲染压力，请谨慎开启！\n开启后可使用「ww抽卡百连」命令，连续抽取100次（10次十连）并发送",
        data=False,
    ),
    "GachaSimBailianMerge": GsBoolConfig(
        title="百连合并转发",
        desc="百连结果使用合并转发发送（关闭则将图片拼合成一条消息后发送）",
        data=True,
    ),
    "GachaSimMasterUnlimited": GsBoolConfig(
        title="主人无限抽取",
        desc="开启后，主人（pm<=1）不受每日抽卡次数限制",
        data=True,
    ),
    "GachaSimEnabled": GsBoolConfig(
        title="模拟抽卡总开关",
        desc="关闭后所有模拟抽卡命令不可用",
        data=True,
    ),
    "GachaSimTextFallback": GsBoolConfig(
        title="渲染失败时使用文本",
        desc="HTML图片渲染失败时，自动回退为纯文本发送结果",
        data=True,
    ),
    "GachaSimRemoteRenderEnable": GsBoolConfig(
        title="外置渲染开关",
        desc="开启后将使用外置渲染服务进行HTML渲染，失败时自动回退到本地渲染",
        data=False,
    ),
    "GachaSimRemoteRenderUrl": GsStrConfig(
        title="外置渲染地址",
        desc="外置渲染服务的API地址，例如：http://127.0.0.1:3000/render",
        data="http://127.0.0.1:3000/render",
    ),
    "GachaSimFontCssUrl": GsStrConfig(
        title="外置渲染字体CSS地址",
        desc="用于HTML渲染的字体CSS URL，外置渲染时传递",
        data="https://fonts.loli.net/css2?family=JetBrains+Mono:wght@500;700&family=Oswald:wght@500;700&family=Noto+Sans+SC:wght@400;700&family=Noto+Color+Emoji&display=swap",
    ),
    "GachaSimPoolMode": GsStrConfig(
        title="卡池选择模式",
        desc="跟随接口: 使用API当期所有卡池；手动指定: 管理员在下方指定可用的UP角色卡池",
        data="跟随接口",
        options=["跟随接口", "手动指定"],
    ),
    "GachaSimManualPool1": GsStrConfig(
        title="手动卡池1 (角色名)",
        desc="手动指定模式下的卡池1，填写UP角色名（如：今汐）。留空时自动使用当期UP角色。武器池自动关联同期",
        data="",
    ),
    "GachaSimManualPool2": GsStrConfig(
        title="手动卡池2 (角色名)",
        desc="手动指定模式下的卡池2，留空表示不启用",
        data="",
    ),
    "GachaSimManualPool3": GsStrConfig(
        title="手动卡池3 (角色名)",
        desc="手动指定模式下的卡池3，留空表示不启用",
        data="",
    ),
    "GachaSimUserSwitchAll": GsBoolConfig(
        title="用户可切换全部卡池",
        desc="开启: 用户可自由切换所有限定池；关闭: 用户只能在配置范围内选择",
        data=True,
    ),
    "GachaSimInjectHelp": GsBoolConfig(
        title="是否强兼xw",
        desc="开启后在ww帮助内插入抽卡帮助（需安装XutheringWavesUID插件，开启与关闭需重启才可生效）",
        data=False,
    ),
}

GachaSimConfig = StringConfig(
    "鸣潮模拟抽卡",
    GACHA_SIM_CONFIG_PATH,
    GACHA_SIM_CONFIG_DEFAULT,
)
