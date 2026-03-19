"""鸣潮抽卡模拟器 - 渲染抽卡结果图片"""
import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from gsuid_core.data_store import get_res_path
from gsuid_core.logger import logger

from .gacha_sim_config import GachaSimConfig

try:
    from XutheringWavesUID.XutheringWavesUID.utils.render_utils import (
        render_html,
        image_to_base64,
    )
    from XutheringWavesUID.XutheringWavesUID.utils.resource.RESOURCE_PATH import (
        ROLE_PILE_PATH,
        WEAPON_PATH,
        AVATAR_PATH,
    )
    from XutheringWavesUID.XutheringWavesUID.utils.name_convert import (
        char_name_to_char_id,
        weapon_name_to_weapon_id,
    )
except ImportError as e:
    logger.warning(f"[模拟抽卡] 渲染模块导入失败: {e}")
    render_html = None
    image_to_base64 = None
    ROLE_PILE_PATH = None
    WEAPON_PATH = None
    AVATAR_PATH = None
    char_name_to_char_id = None
    weapon_name_to_weapon_id = None

# 检查本地渲染依赖
try:
    from jinja2 import Environment as _check_jinja  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False
    logger.warning("[模拟抽卡] 未安装 jinja2，HTML模板渲染不可用。")
    logger.info("[模拟抽卡] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install jinja2")
    logger.info("[模拟抽卡] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install jinja2")

try:
    from playwright.async_api import async_playwright as _check_pw  # noqa: F401
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# 启动时输出依赖状态
if render_html is None:
    logger.warning("[模拟抽卡] XutheringWavesUID 渲染模块不可用，本地渲染将不可用。请确保安装了 XutheringWavesUID 插件，或开启外置渲染。")
if not _PLAYWRIGHT_AVAILABLE and render_html is not None:
    logger.warning("[模拟抽卡] 未安装 playwright，本地HTML截图渲染不可用。")
    logger.info("[模拟抽卡] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install playwright && uv run playwright install chromium")
    logger.info("[模拟抽卡] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install playwright; uv run playwright install chromium")

# 资源目录
PLUGIN_DIR = Path(__file__).parent
TEMPLATE_DIR = PLUGIN_DIR / "templates"
TEXTURE_DIR = PLUGIN_DIR / "texture2d"
WEAPON_TYPE_ICON_DIR = TEMPLATE_DIR / "assets" / "weapon_type"
ELEMENT_TYPE_ICON_DIR = TEMPLATE_DIR / "assets" / "element_type"

# Jinja2 Environment
try:
    from jinja2 import Environment, FileSystemLoader

    gacha_sim_templates = Environment(
        loader=FileSystemLoader([str(TEMPLATE_DIR)])
    )
except Exception:
    gacha_sim_templates = None


def _file_to_data_url(fp: Path, mime: str = "image/png") -> str:
    """文件转 data URL"""
    if not fp.exists():
        return ""
    data = fp.read_bytes()
    b64 = base64.b64encode(data).decode()
    return f"data:{mime};base64,{b64}"


# 武器子类型缓存
_weapon_type_cache: Dict[str, int] = {}

# 武器类型图标缓存 (type_id -> base64 data URL)
_weapon_type_icon_cache: Dict[int, str] = {}

# 武器类型图标文件名映射
_WEAPON_TYPE_ICON_FILES = {
    1: "1_broadblade.png",  # 长刃
    2: "2_sword.png",       # 迅刀
    3: "3_pistols.png",     # 佩枪
    4: "4_gauntlets.png",   # 臂铠
    5: "5_rectifier.png",   # 音感仪
}

# attributeId 到元素名称的映射
_ATTRIBUTE_ID_TO_ELEMENT = {
    1: "冷凝",
    2: "热熔",
    3: "导电",
    4: "气动",
    5: "衍射",
    6: "湮灭",
}


def _get_weapon_type_icons() -> Dict[int, str]:
    """
    加载武器类型图标为 base64 data URL。
    图标来源: astrbot_plugin_ww_gacha_sim (白色透明底PNG)
    """
    global _weapon_type_icon_cache
    if _weapon_type_icon_cache:
        return _weapon_type_icon_cache

    for type_id, filename in _WEAPON_TYPE_ICON_FILES.items():
        icon_path = WEAPON_TYPE_ICON_DIR / filename
        if icon_path.exists():
            _weapon_type_icon_cache[type_id] = _file_to_data_url(
                icon_path, "image/png"
            )

    logger.debug(f"[模拟抽卡] 已加载 {len(_weapon_type_icon_cache)} 个武器类型图标")
    return _weapon_type_icon_cache


# 元素类型图标缓存 (attributeId -> base64 data URL)
_element_type_icon_cache: Dict[int, str] = {}


def _get_element_type_icons() -> Dict[int, str]:
    """加载角色元素类型图标为 base64 data URL"""
    global _element_type_icon_cache
    if _element_type_icon_cache:
        return _element_type_icon_cache

    for attr_id, element_name in _ATTRIBUTE_ID_TO_ELEMENT.items():
        icon_path = ELEMENT_TYPE_ICON_DIR / f"attr_simple_{element_name}.png"
        if icon_path.exists():
            _element_type_icon_cache[attr_id] = _file_to_data_url(icon_path, "image/png")

    logger.debug(f"[模拟抽卡] 已加载 {len(_element_type_icon_cache)} 个元素类型图标")
    return _element_type_icon_cache


def _load_weapon_types() -> Dict[str, int]:
    """
    加载武器子类型信息。
    从 XutheringWavesUID 的 weapon detail JSON 文件中读取。
    返回: {weapon_name: type} (type: 1=长刃, 2=迅刀, 3=佩枪, 4=臂铠, 5=音感仪)
    """
    global _weapon_type_cache
    if _weapon_type_cache:
        return _weapon_type_cache

    try:
        # 获取武器数据路径
        xwuid_path = get_res_path() / "XutheringWavesUID" / "resource" / "map" / "detail_json" / "weapon"
        if not xwuid_path.exists():
            logger.warning("[模拟抽卡] 武器详情数据目录不存在")
            return {}

        # 遍历所有 JSON 文件
        for json_file in xwuid_path.glob("*.json"):
            try:
                import json
                data = json.loads(json_file.read_text(encoding="utf-8"))
                name = data.get("name", "")
                wtype = data.get("type", 0)
                if name and wtype:
                    _weapon_type_cache[name] = wtype
            except Exception:
                continue

        logger.debug(f"[模拟抽卡] 已加载 {len(_weapon_type_cache)} 个武器子类型信息")
    except Exception as e:
        logger.warning(f"[模拟抽卡] 加载武器子类型失败: {e}")

    return _weapon_type_cache


def _get_weapon_subtype(weapon_name: str) -> int:
    """
    根据武器名称获取子类型。
    Args:
        weapon_name: 武器名称
    Returns:
        0=未找到, 1=长刃, 2=迅刀, 3=佩枪, 4=臂铠, 5=音感仪
    """
    if not weapon_name:
        return 0

    weapon_types = _load_weapon_types()
    return weapon_types.get(weapon_name, 0)


# 角色属性缓存 (char_name -> attributeId)
_char_attr_cache: Dict[str, int] = {}


def _load_char_attributes() -> Dict[str, int]:
    """从 XWUID 的角色 detail JSON 加载 attributeId"""
    global _char_attr_cache
    if _char_attr_cache:
        return _char_attr_cache

    try:
        xwuid_path = get_res_path() / "XutheringWavesUID" / "resource" / "map" / "detail_json" / "char"
        if not xwuid_path.exists():
            logger.warning("[模拟抽卡] 角色详情数据目录不存在")
            return {}

        import json
        for json_file in xwuid_path.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                name = data.get("name", "")
                attr_id = data.get("attributeId", 0)
                if name and attr_id:
                    _char_attr_cache[name] = attr_id
            except Exception:
                continue

        logger.debug(f"[模拟抽卡] 已加载 {len(_char_attr_cache)} 个角色属性信息")
    except Exception as e:
        logger.warning(f"[模拟抽卡] 加载角色属性失败: {e}")

    return _char_attr_cache


def _get_char_element(char_name: str) -> int:
    """获取角色的元素属性 attributeId (0=未找到, 1=冷凝...6=湮灭)"""
    if not char_name:
        return 0
    char_attrs = _load_char_attributes()
    return char_attrs.get(char_name, 0)


# 卡框精灵图缓存
_card_frame_cache: Dict[str, str] = {}

CARD_FRAMES_DIR = TEMPLATE_DIR / "assets" / "card_frames"


def _get_card_frame_images() -> Dict[str, str]:
    """加载卡框精灵图为 base64 data URL"""
    global _card_frame_cache
    if _card_frame_cache:
        return _card_frame_cache

    frame_files = {
        "bg_3": "bg_star_3star.png",
        "bg_4": "bg_star_4star.png",
        "bg_5": "bg_star_5star.png",
        "show_3": "show_star_3star.png",
        "show_4": "show_star_4star.png",
        "show_5": "show_star_5star.png",
    }

    for key, filename in frame_files.items():
        fp = CARD_FRAMES_DIR / filename
        if fp.exists():
            _card_frame_cache[key] = _file_to_data_url(fp, "image/png")

    # 半调图案
    bandiao_path = TEMPLATE_DIR / "assets" / "bandiao.png"
    if bandiao_path.exists():
        _card_frame_cache["bandiao"] = _file_to_data_url(bandiao_path, "image/png")

    return _card_frame_cache


def _get_background() -> str:
    """获取背景图 base64"""
    bg_file = TEXTURE_DIR / "beijing.png"
    if not bg_file.exists():
        # fallback to original
        bg_file = TEXTURE_DIR / "background.png"
    return _file_to_data_url(bg_file)


def _find_image(name: str, item_type: str, resource_id: str = "") -> str:
    """
    查找角色/武器图片并转为 base64 data URL。
    - texture2d目录: 角色为 {char_id}.png，武器为 {weapon_id}.png
    - fallback: XutheringWavesUID 的 ROLE_PILE_PATH / WEAPON_PATH
    """
    if image_to_base64 is None:
        return ""

    rid = resource_id

    if item_type == "character":
        if not rid and char_name_to_char_id:
            rid = char_name_to_char_id(name) or ""
        
        # 从texture2d目录查找
        if TEXTURE_DIR.exists() and rid:
            fp = TEXTURE_DIR / f"{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        
        # fallback: XutheringWavesUID
        if rid and ROLE_PILE_PATH:
            fp = ROLE_PILE_PATH / f"role_pile_{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        # fallback: avatar
        if rid and AVATAR_PATH:
            fp = AVATAR_PATH / f"role_head_{rid}.png"
            if fp.exists():
                return image_to_base64(fp)

    elif item_type == "weapon":
        if not rid and weapon_name_to_weapon_id:
            rid = weapon_name_to_weapon_id(name) or ""
        
        # 从texture2d目录查找
        if TEXTURE_DIR.exists() and rid:
            fp = TEXTURE_DIR / f"{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        
        # fallback: XutheringWavesUID
        if rid and WEAPON_PATH:
            fp = WEAPON_PATH / f"weapon_{rid}.png"
            if fp.exists():
                return image_to_base64(fp)

    return ""


async def render_gacha_result(
    results: List[Dict[str, Any]],
    pool_name: str,
    signature_code: str = "",
    draw_type: int = 10,
    nickname: str = "",
    avatar: str = "",
) -> Optional[bytes]:
    """
    渲染抽卡结果为图片

    Args:
        results: 抽卡结果列表
        pool_name: 卡池名称
        signature_code: 用户特征码
        draw_type: 抽卡类型 (1=单抽, 10=十连)
        nickname: 用户昵称
        avatar: 用户头像URL

    Returns:
        图片 bytes, 或 None (渲染失败)
    """
    if gacha_sim_templates is None:
        logger.warning("[模拟抽卡] jinja2 模板引擎不可用")
        return None

    # 检查是否有可用的渲染方式
    remote_render_enable = GachaSimConfig.get_config("GachaSimRemoteRenderEnable").data
    remote_render_url = GachaSimConfig.get_config("GachaSimRemoteRenderUrl").data
    has_remote = remote_render_enable and remote_render_url
    has_local = render_html is not None

    if not has_remote and not has_local:
        logger.warning("[模拟抽卡] 远程渲染未开启且本地渲染模块不可用，无法渲染")
        return None

    # 卡片素材
    bg_image = _get_background()
    weapon_type_icons = _get_weapon_type_icons()
    element_type_icons = _get_element_type_icons()
    card_frames = _get_card_frame_images()

    # 为每个结果填充图片
    items = []
    for r in results:
        item = {
            "star": r["star"],
            "name": r["name"],
            "is_up": r.get("is_up", False),
            "type": r.get("type", "character"),
            "pity_count": r.get("pity_count", 0),
            "image": _find_image(
                r["name"],
                r.get("type", "character"),
                r.get("resource_id", ""),
            ),
            "weapon_type": _get_weapon_subtype(r["name"]) if r.get("type") == "weapon" else 0,
            "element_type": _get_char_element(r["name"]) if r.get("type") == "character" else 0,
        }
        items.append(item)

    # 排序: 当期UP五星 > 非UP五星 > 当期UP四星 > 非UP四星 > 三星
    def _sort_key(item):
        s = item["star"]
        up = item["is_up"]
        if s == 5 and up:
            return 0
        elif s == 5 and not up:
            return 1
        elif s == 4 and up:
            return 2
        elif s == 4 and not up:
            return 3
        else:
            return 4

    items.sort(key=_sort_key)

    context = {
        "pool_name": pool_name,
        "items": items,
        "draw_type": draw_type,
        "total_count": len(results),
        "bg_image": bg_image,
        "signature_code": signature_code,
        "nickname": nickname,
        "avatar": avatar,
        "weapon_type_icons": weapon_type_icons,
        "element_type_icons": element_type_icons,
        "card_frames": card_frames,
    }

    # 远程渲染配置
    font_css_url = GachaSimConfig.get_config("GachaSimFontCssUrl").data

    # 尝试远程渲染（如果开启）
    if has_remote:
        try:
            # 设置字体 CSS URL
            context["font_css_url"] = font_css_url

            # 渲染 HTML 模板为字符串
            template = gacha_sim_templates.get_template("gacha_result.html")
            html_content = template.render(**context)

            # 调用远程渲染服务
            import time as _time
            _start = _time.time()
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    remote_render_url,
                    json={"html": html_content},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    _elapsed = _time.time() - _start
                    logger.info(
                        f"[模拟抽卡] 远程渲染成功，耗时: {_elapsed:.2f}s，"
                        f"图片大小: {len(response.content)} bytes"
                    )
                    return response.content
                else:
                    logger.warning(
                        f"[模拟抽卡] 远程渲染失败: HTTP {response.status_code}, "
                        f"响应: {response.text[:200]}"
                    )
        except httpx.TimeoutException:
            logger.warning("[模拟抽卡] 远程渲染超时，将回退到本地渲染")
        except Exception as e:
            logger.warning(f"[模拟抽卡] 远程渲染异常: {e}, 将回退到本地渲染")

    # 本地渲染（默认或远程失败时回退）
    if not has_local:
        logger.warning("[模拟抽卡] 远程渲染失败且本地渲染模块不可用")
        return None

    try:
        img_bytes = await render_html(
            gacha_sim_templates,
            "gacha_result.html",
            context,
        )
        return img_bytes
    except Exception as e:
        logger.error(f"[模拟抽卡] 渲染失败: {e}")
        return None


def format_text_result(
    results: List[Dict[str, Any]],
    pool_name: str,
    signature_code: str = "",
) -> str:
    """纯文本格式的抽卡结果（渲染失败时的 fallback）"""
    lines = [f"【{pool_name}】\n"]

    for r in results:
        star_emoji = "⭐" * r["star"]
        up_tag = " [UP]" if r.get("is_up") else ""
        type_tag = "🗡️" if r.get("type") == "weapon" else "👤"
        lines.append(f"{star_emoji} {type_tag}{r['name']}{up_tag}")

    star5 = [r for r in results if r["star"] == 5]
    if star5:
        lines.append("")
        for r in star5:
            lines.append(f"✨ {r['name']} - 第{r.get('pity_count', '?')}抽")

    if signature_code:
        lines.append(f"\n特征码: {signature_code}")

    return "\n".join(lines)


async def render_pool_select(
    char_pools: List[Dict[str, Any]],
    weapon_pools: List[Dict[str, Any]],
    selected_char_id: str = "",
    selected_weapon_id: str = "",
    start_index: int = 1,
    prefix: str = "ww",
) -> Optional[bytes]:
    """
    渲染卡池选择界面图片

    Args:
        char_pools: 限定角色卡池列表
        weapon_pools: 限定武器卡池列表
        selected_char_id: 当前选中的角色卡池ID
        selected_weapon_id: 当前选中的武器卡池ID
        start_index: 起始编号
        prefix: 命令前缀

    Returns:
        图片 bytes, 或 None (渲染失败)
    """
    if gacha_sim_templates is None:
        logger.warning("[模拟抽卡] jinja2 模板引擎不可用")
        return None

    # 检查是否有可用的渲染方式
    remote_render_enable = GachaSimConfig.get_config("GachaSimRemoteRenderEnable").data
    remote_render_url = GachaSimConfig.get_config("GachaSimRemoteRenderUrl").data
    has_remote = remote_render_enable and remote_render_url
    has_local = render_html is not None

    if not has_remote and not has_local:
        logger.warning("[模拟抽卡] 远程渲染未开启且本地渲染模块不可用，无法渲染")
        return None

    # 构造模板数据
    idx = start_index
    char_pool_data = []
    for p in char_pools:
        up5_names = "、".join([item["name"] for item in p.get("up", {}).get("5star", [])])
        # 简化时间显示
        start_time = p.get("startTime", "")
        end_time = p.get("endTime", "")
        if start_time and end_time:
            # 只取日期部分
            start_date = start_time.split(" ")[0] if " " in start_time else start_time
            end_date = end_time.split(" ")[0] if " " in end_time else end_time
            time_range = f"{start_date} ~ {end_date}"
        else:
            time_range = ""

        char_pool_data.append({
            "index": idx,
            "id": p.get("id", ""),
            "name": p.get("name", "未知"),
            "pic": p.get("pic", ""),
            "up5_names": up5_names,
            "time_range": time_range,
        })
        idx += 1

    weapon_pool_data = []
    for p in weapon_pools:
        up5_names = "、".join([item["name"] for item in p.get("up", {}).get("5star", [])])
        start_time = p.get("startTime", "")
        end_time = p.get("endTime", "")
        if start_time and end_time:
            start_date = start_time.split(" ")[0] if " " in start_time else start_time
            end_date = end_time.split(" ")[0] if " " in end_time else end_time
            time_range = f"{start_date} ~ {end_date}"
        else:
            time_range = ""

        weapon_pool_data.append({
            "index": idx,
            "id": p.get("id", ""),
            "name": p.get("name", "未知"),
            "pic": p.get("pic", ""),
            "up5_names": up5_names,
            "time_range": time_range,
        })
        idx += 1

    context = {
        "char_pools": char_pool_data,
        "weapon_pools": weapon_pool_data,
        "selected_char_id": selected_char_id,
        "selected_weapon_id": selected_weapon_id,
        "prefix": prefix,
    }

    # 远程渲染配置
    font_css_url = GachaSimConfig.get_config("GachaSimFontCssUrl").data

    # 尝试远程渲染
    if has_remote:
        try:
            context["font_css_url"] = font_css_url
            template = gacha_sim_templates.get_template("pool_select.html")
            html_content = template.render(**context)

            import time as _time
            _start = _time.time()
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    remote_render_url,
                    json={"html": html_content},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    _elapsed = _time.time() - _start
                    logger.info(
                        f"[模拟抽卡] 卡池选择远程渲染成功，耗时: {_elapsed:.2f}s"
                    )
                    return response.content
                else:
                    logger.warning(
                        f"[模拟抽卡] 卡池选择远程渲染失败: HTTP {response.status_code}"
                    )
        except Exception as e:
            logger.warning(f"[模拟抽卡] 卡池选择远程渲染异常: {e}")

    # 本地渲染
    if not has_local:
        return None

    try:
        img_bytes = await render_html(
            gacha_sim_templates,
            "pool_select.html",
            context,
        )
        return img_bytes
    except Exception as e:
        logger.error(f"[模拟抽卡] 卡池选择渲染失败: {e}")
        return None


# ============================================================
# 模拟抽卡记录图片渲染（xwuid风格）
# ============================================================

async def render_gacha_log_image(
    records: List[Dict[str, Any]],
    signature_code: str = "",
    pool_name: str = "全部卡池",
) -> Optional[bytes]:
    """
    渲染模拟抽卡记录为图片（xwuid同款样式）

    Args:
        records: 5星历史记录列表
        signature_code: 用户特征码
        pool_name: 卡池名称

    Returns:
        图片 bytes, 或 None (渲染失败)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import math
    except ImportError:
        logger.warning("[模拟抽卡] PIL 不可用，无法渲染抽卡记录图片")
        return None

    # 颜色定义
    GOLD = (255, 215, 0)
    PURPLE = (180, 124, 252)
    BLUE = (100, 149, 237)
    WHITE = (255, 255, 255)
    DARK_BG = (25, 25, 35)
    SECTION_BG = (35, 35, 50)
    GRAY = (157, 157, 157)
    LIGHT_GRAY = (180, 180, 180)

    # 尺寸参数
    CARD_W = 130
    CARD_H = 130
    CARDS_PER_ROW = 5
    CARD_GAP = 15
    SECTION_H = 280  # 每个卡池区块高度
    HEADER_H = 120
    FOOTER_H = 60

    if not records:
        # 空记录图
        h = 400
        img = Image.new('RGB', (1000, h), DARK_BG)
        draw = ImageDraw.Draw(img)
        try:
            font_large = ImageFont.truetype("msyh.ttc", 40)
            font_small = ImageFont.truetype("msyh.ttc", 24)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = font_large
        draw.text((500, 160), "模拟抽卡", GOLD, font_large, "mm")
        draw.text((500, 220), "暂无抽卡记录", GRAY, font_small, "mm")
        draw.text((500, 270), "进行模拟抽卡后将显示记录", GRAY, font_small, "mm")
        if signature_code:
            draw.text((500, 340), f"特征码: {signature_code}", GOLD, font_small, "mm")
        buf = BytesIO()
        img.save(buf, format='PNG', quality=95)
        return buf.getvalue()

    # 按卡池分组
    pools_data: Dict[str, List] = {}
    for r in records:
        pt = r.get('pool_type', 'unknown')
        if pt not in pools_data:
            pools_data[pt] = []
        pools_data[pt].append(r)

    # 计算图片高度
    pool_count = len(pools_data)
    total_height = HEADER_H + pool_count * SECTION_H + FOOTER_H

    img = Image.new('RGB', (1000, total_height), DARK_BG)
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("msyh.ttc", 36)
        font_bold = ImageFont.truetype("msyh.ttc", 24)
        font_normal = ImageFont.truetype("msyh.ttc", 20)
        font_small = ImageFont.truetype("msyh.ttc", 16)
    except Exception:
        font_title = font_bold = font_normal = font_small = ImageFont.load_default()

    # 顶部标题栏
    for y in range(HEADER_H):
        alpha = int(30 * (1 - y / HEADER_H))
        draw.rectangle([(0, y), (1000, y + 1)],
                      fill=(40 + alpha, 35 + alpha, 55 + alpha))

    # "模拟抽卡"红色标签
    draw.rectangle([(30, 25), (200, 65)], fill=(200, 60, 60))
    draw.text((115, 45), "模拟抽卡", WHITE, font_title, "mm")

    # 统计信息
    total_5star = len(records)
    total_pulls = sum(r.get('pity_count', 0) for r in records) or 0
    avg_pity = round(total_pulls / total_5star, 1) if total_5star > 0 else 0
    up_count = len([r for r in records if r.get('is_up', False)])

    draw.text((970, 35), f"五星: {total_5star}  平均:{avg_pity}抽  UP:{up_count}",
              LIGHT_GRAY, font_normal, "rm")

    # 特征码
    if signature_code:
        draw.text((970, 65), f"特征码: {signature_code}", GOLD, font_normal, "rm")

    # 分隔线
    draw.line([(30, HEADER_H - 10), (970, HEADER_H - 10)], fill=(60, 60, 80), width=2)

    # 卡池名称映射
    POOL_NAMES = {
        'limited_char': '限定角色池',
        'limited_weapon': '限定武器池',
        'standard_char': '常驻角色池',
        'standard_weapon': '常驻武器池',
    }

    # 绘制每个卡池区块
    y_offset = HEADER_H
    for pool_type, pool_records in pools_data.items():
        pool_display_name = POOL_NAMES.get(pool_type, pool_type)

        # 区块背景
        draw.rectangle([(30, y_offset), (970, y_offset + SECTION_H - 20)],
                       fill=SECTION_BG)

        # 卡池名称
        draw.text((50, y_offset + 30), pool_display_name, WHITE, font_bold, "lm")

        # 统计
        pool_up = len([r for r in pool_records if r.get('is_up', False)])
        draw.text((970, y_offset + 30), f"五星:{len(pool_records)}  UP:{pool_up}",
                  LIGHT_GRAY, font_normal, "rm")

        # 分隔线
        draw.line([(50, y_offset + 65), (950, y_offset + 65)],
                  fill=(60, 60, 80), width=1)

        # 绘制5星卡片（最新的在前）
        sorted_records = sorted(pool_records, key=lambda x: x.get('created_at', 0), reverse=True)
        for idx, record in enumerate(sorted_records[:10]):  # 最多显示10个
            cx = 50 + (idx % CARDS_PER_ROW) * (CARD_W + CARD_GAP)
            cy = y_offset + 80 + (idx // CARDS_PER_ROW) * (CARD_H + 10)

            # 卡片背景
            star = record.get('star', 5)
            if star == 5:
                card_color = GOLD
            elif star == 4:
                card_color = PURPLE
            else:
                card_color = BLUE

            # 简化卡片：只显示名称和抽数
            card_bg = Image.new('RGB', (CARD_W, CARD_H - 20), (40, 40, 55))
            card_draw = ImageDraw.Draw(card_bg)

            # 星级标签
            star_text = "★" * star
            card_draw.text((CARD_W // 2, 15), star_text, card_color, font_small, "mm")

            # 名称
            name = record.get('name', '?')
            if len(name) > 5:
                name = name[:5] + '…'
            card_draw.text((CARD_W // 2, 45), name, WHITE, font_small, "mm")

            # 抽数
            pity = record.get('pity_count', 0)
            if pity:
                pity_color = (255, 80, 80) if pity >= 70 else (100, 200, 100) if pity <= 40 else WHITE
                card_draw.text((CARD_W // 2, 75), f"{pity}抽", pity_color, font_small, "mm")

            # UP标签
            if record.get('is_up', False):
                draw.rectangle([(cx + CARD_W - 30, cy), (cx + CARD_W, cy + 20)],
                              fill=(255, 60, 60))
                draw.text((cx + CARD_W - 15, cy + 10), "UP", WHITE, ImageFont.load_default(), "mm")

            img.paste(card_bg, (cx, cy))

        y_offset += SECTION_H

    # 底部提示
    if len(records) > 10 * len(pools_data):
        draw.text((500, total_height - 35),
                  f"... 还有 {len(records) - 10 * len(pools_data)} 条记录未显示",
                  GRAY, font_small, "mm")

    buf = BytesIO()
    img.save(buf, format='PNG', quality=95)
    return buf.getvalue()

