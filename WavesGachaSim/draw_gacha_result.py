"""鸣潮抽卡模拟器 - 渲染抽卡结果图片"""
import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _file_to_data_url(fp: Path, mime: str = None) -> str:
    """文件转 data URL，自动从扩展名检测 MIME 类型"""
    if not fp.exists():
        return ""
    if mime is None:
        ext = fp.suffix.lower()
        if ext == ".webp":
            mime = "image/webp"
        elif ext == ".jpg" or ext == ".jpeg":
            mime = "image/jpeg"
        elif ext == ".gif":
            mime = "image/gif"
        else:
            mime = "image/png"
    data = fp.read_bytes()
    b64 = base64.b64encode(data).decode()
    return f"data:{mime};base64,{b64}"


# 武器子类型缓存
_weapon_type_cache: Dict[str, int] = {}

# 武器类型图标缓存 (type_id -> base64 data URL)
_weapon_type_icon_cache: Dict[int, str] = {}

# 武器类型图标文件名映射
_WEAPON_TYPE_ICON_FILES = {
    1: "1_broadblade",  # 长刃
    2: "2_sword",       # 迅刀
    3: "3_pistols",     # 佩枪
    4: "4_gauntlets",   # 臂铠
    5: "5_rectifier",   # 音感仪
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

    for type_id, basename in _WEAPON_TYPE_ICON_FILES.items():
        icon_path = WEAPON_TYPE_ICON_DIR / f"{basename}.webp"
        if not icon_path.exists():
            icon_path = WEAPON_TYPE_ICON_DIR / f"{basename}.png"
        if icon_path.exists():
            _weapon_type_icon_cache[type_id] = _file_to_data_url(icon_path)

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
        icon_path = ELEMENT_TYPE_ICON_DIR / f"attr_simple_{element_name}.webp"
        if not icon_path.exists():
            icon_path = ELEMENT_TYPE_ICON_DIR / f"attr_simple_{element_name}.png"
        if icon_path.exists():
            _element_type_icon_cache[attr_id] = _file_to_data_url(icon_path)

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
        "bg_3": "bg_star_3star",
        "bg_4": "bg_star_4star",
        "bg_5": "bg_star_5star",
        "show_3": "show_star_3star",
        "show_4": "show_star_4star",
        "show_5": "show_star_5star",
    }

    for key, basename in frame_files.items():
        # 优先 webp，其次 png
        fp = CARD_FRAMES_DIR / f"{basename}.webp"
        if not fp.exists():
            fp = CARD_FRAMES_DIR / f"{basename}.png"
        if fp.exists():
            _card_frame_cache[key] = _file_to_data_url(fp)

    # 半调图案
    bandiao_path = TEMPLATE_DIR / "assets" / "bandiao.webp"
    if not bandiao_path.exists():
        bandiao_path = TEMPLATE_DIR / "assets" / "bandiao.png"
    if bandiao_path.exists():
        _card_frame_cache["bandiao"] = _file_to_data_url(bandiao_path, "image/png")

    return _card_frame_cache


def _get_background() -> str:
    """获取背景图 base64"""
    bg_file = TEXTURE_DIR / "beijing.webp"
    if not bg_file.exists():
        bg_file = TEXTURE_DIR / "beijing.png"
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
        
        # 从texture2d目录查找（优先 webp > png）
        if TEXTURE_DIR.exists() and rid:
            fp = TEXTURE_DIR / f"{rid}.webp"
            if fp.exists():
                return image_to_base64(fp)
            fp = TEXTURE_DIR / f"{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        
        # fallback: XutheringWavesUID
        if rid and ROLE_PILE_PATH:
            fp = ROLE_PILE_PATH / f"role_pile_{rid}.webp"
            if fp.exists():
                return image_to_base64(fp)
            fp = ROLE_PILE_PATH / f"role_pile_{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        # fallback: avatar
        if rid and AVATAR_PATH:
            fp = AVATAR_PATH / f"role_head_{rid}.webp"
            if fp.exists():
                return image_to_base64(fp)
            fp = AVATAR_PATH / f"role_head_{rid}.png"
            if fp.exists():
                return image_to_base64(fp)

    elif item_type == "weapon":
        if not rid and weapon_name_to_weapon_id:
            rid = weapon_name_to_weapon_id(name) or ""
        
        # 从texture2d目录查找（优先 webp > png）
        if TEXTURE_DIR.exists() and rid:
            fp = TEXTURE_DIR / f"{rid}.webp"
            if fp.exists():
                return image_to_base64(fp)
            fp = TEXTURE_DIR / f"{rid}.png"
            if fp.exists():
                return image_to_base64(fp)
        
        # fallback: XutheringWavesUID
        if rid and WEAPON_PATH:
            fp = WEAPON_PATH / f"weapon_{rid}.webp"
            if fp.exists():
                return image_to_base64(fp)
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
            context["font_css_url"] = font_css_url

            # 渲染 HTML 模板为字符串
            template = gacha_sim_templates.get_template("gacha_result.html")
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
    char_idx = start_index
    weapon_idx = 1
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
            "index": char_idx,
            "id": p.get("id", ""),
            "name": p.get("name", "未知"),
            "pic": p.get("pic", ""),
            "up5_names": up5_names,
            "time_range": time_range,
            "pool_type": "char",
        })
        char_idx += 1

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
            "index": weapon_idx,
            "id": p.get("id", ""),
            "name": p.get("name", "未知"),
            "pic": p.get("pic", ""),
            "up5_names": up5_names,
            "time_range": time_range,
            "pool_type": "weapon",
        })
        weapon_idx += 1

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



# 模拟抽卡记录图片渲染（xwuid同款样式）


# XutheringWavesUID 资源路径
_XW_UID_TEXTURE_PATH = Path(__file__).parent.parent.parent / "XutheringWavesUID" / "XutheringWavesUID" / "wutheringwaves_gachalog" / "texture2d"

HOMO_TAG = ["非到极致", "运气不好", "平稳保底", "小欧一把", "欧狗在此"]

gacha_type_meta_rename = {
    "limited_char": "限定角色调谐",
    "limited_weapon": "限定武器调谐",
    "standard_char": "角色常驻调谐",
    "standard_weapon": "武器常驻调谐",
}


def _get_level_from_list(ast: int, lst: List) -> int:
    if ast == 0:
        return 2
    for num_index, num in enumerate(lst):
        if ast <= num:
            level = 4 - num_index
            break
    else:
        level = 0
    return level


def _format_timestamp(ts: int) -> str:
    """将时间戳转换为 YYYY-MM-DD HH:MM:SS 格式"""
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


async def render_gacha_log_image(
    records: List[Dict[str, Any]],
    signature_code: str = "",
) -> Optional[bytes]:
    """
    渲染模拟抽卡记录为图片（xwuid同款样式）

    Args:
        records: 5星历史记录列表
        signature_code: 用户特征码

    Returns:
        图片 bytes, 或 None (渲染失败)
    """
    try:
        from PIL import Image, ImageDraw
        import random
        import math
    except ImportError:
        logger.warning("[模拟抽卡] PIL 不可用，无法渲染抽卡记录图片")
        return None

    # 尝试导入 XutheringWavesUID 字体和工具
    try:
        from XutheringWavesUID.XutheringWavesUID.utils.fonts.waves_fonts import (
            waves_font_18,
            waves_font_20,
            waves_font_23,
            waves_font_24,
            waves_font_25,
            waves_font_30,
            waves_font_32,
            waves_font_40,
        )
        from gsuid_core.utils.image.convert import convert_img
        from gsuid_core.utils.image.image_tools import crop_center_img
        from XutheringWavesUID.XutheringWavesUID.utils.image import (
            get_waves_bg,
            add_footer,
            get_square_avatar,
            get_square_weapon,
            cropped_square_avatar,
        )
        from XutheringWavesUID.XutheringWavesUID.utils.resource.RESOURCE_PATH import AVATAR_PATH
        _XW_UID_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"[模拟抽卡] XutheringWavesUID 渲染资源不可用: {e}")
        _XW_UID_AVAILABLE = False

    # 颜色
    GOLD = (255, 215, 0)
    WHITE = (255, 255, 255)
    GRAY = (157, 157, 157)

    if not records:
        h = 400
        img = Image.new("RGB", (1000, h), (25, 25, 35))
        draw = ImageDraw.Draw(img)
        if _XW_UID_AVAILABLE:
            draw.text((500, 160), "模拟抽卡", GOLD, waves_font_40, "mm")
            draw.text((500, 220), "暂无抽卡记录", GRAY, waves_font_20, "mm")
            draw.text((500, 270), "进行模拟抽卡后将显示记录", GRAY, waves_font_20, "mm")
            if signature_code:
                draw.text((500, 340), f"特征码: {signature_code}", GOLD, waves_font_25, "mm")
        else:
            draw.text((500, 200), "模拟抽卡 - 暂无记录", WHITE, ImageFont.load_default(), "mm")
        buf = BytesIO()
        img.save(buf, format="PNG", quality=95)
        return buf.getvalue()

    # 将 WavesGachaSim 记录转换为 xwuid 格式
    # WavesGachaSim: name, star, item_type, is_up, pity_count, pool_type, created_at
    # xwuid格式: name, resourceType, resourceId, qualityLevel, is_up, gacha_num, time

    # 按卡池分组，统计每个卡池
    pools_data: Dict[str, Dict] = {}
    for r in records:
        pt = r.get("pool_type", "unknown")
        if pt not in pools_data:
            pools_data[pt] = {
                "total": 0,
                "avg": 0,
                "avg_up": 0,
                "remain": 0,
                "r_num": [],
                "up_list": [],
                "rank_s_list": [],
                "time_range": "",
                "all_time": "",
                "level": 0,
            }

    for pt, pool_d in pools_data.items():
        num = 1
        pool_records = [r for r in records if r.get("pool_type") == pt]
        for record in pool_records:
            record["time"] = _format_timestamp(record.get("created_at", 0))
            # 转换字段名以匹配 xwuid 格式
            record["qualityLevel"] = record.get("star", 5)
            record["resourceType"] = "武器" if record.get("type") == "weapon" else "角色"
            # 查找 resourceId
            rid = record.get("resource_id", "")
            if not rid:
                if record.get("type") == "weapon" and weapon_name_to_weapon_id:
                    rid = weapon_name_to_weapon_id(record["name"]) or ""
                elif record.get("type") == "character" and char_name_to_char_id:
                    rid = char_name_to_char_id(record["name"]) or ""
            record["resourceId"] = rid

            if record["qualityLevel"] == 5:
                record["gacha_num"] = num
                pool_d["r_num"].append(num)
                pool_d["rank_s_list"].append(record)
                if record.get("is_up"):
                    pool_d["up_list"].append(record)
                num = 1
            else:
                num += 1
            pool_d["total"] += 1
        pool_d["remain"] = num - 1

    # 计算各卡池平均值和等级
    POOL_LEVEL_LST = {
        "limited_char": [74, 87, 99, 105, 120],
        "standard_char": [45, 52, 59, 65, 70],
        "standard_weapon": [45, 52, 59, 65, 70],
        "limited_weapon": [45, 52, 59, 65, 70],
    }

    for pt, pool_d in pools_data.items():
        if pool_d["rank_s_list"]:
            _d = sum(pool_d["r_num"]) / len(pool_d["r_num"])
            pool_d["avg"] = float(f"{_d:.2f}")
        if pool_d["up_list"]:
            _u = sum(pool_d["r_num"]) / len(pool_d["up_list"])
            pool_d["avg_up"] = float(f"{_u:.2f}")

        pool_d["level"] = 2
        lvl_lst = POOL_LEVEL_LST.get(pt, [45, 52, 59, 65, 70])
        if pool_d["avg_up"] != 0:
            pool_d["level"] = _get_level_from_list(pool_d["avg_up"], lvl_lst)
        elif pool_d["avg"] != 0:
            pool_d["level"] = _get_level_from_list(pool_d["avg"], lvl_lst)

    # 计算布局尺寸
    oset = 280
    bset = 170

    _numlen = 0
    for name in pools_data:
        _num = len(pools_data[name]["rank_s_list"])
        if _num == 0:
            _numlen += 50
        else:
            _numlen += bset * ((_num - 1) // 5 + 1)

    _header = 380
    footer = 50
    pool_count = len(pools_data)
    w, h = 1000, _header + pool_count * oset + _numlen + footer

    if _XW_UID_AVAILABLE:
        card_img = get_waves_bg(w, h)
    else:
        card_img = Image.new("RGB", (w, h), (25, 25, 35))
    card_draw = ImageDraw.Draw(card_img)

    # 加载纹理资源
    if _XW_UID_AVAILABLE:
        item_fg = Image.open(_XW_UID_TEXTURE_PATH / "char_bg.png").convert("RGBA")
        up_icon = Image.open(_XW_UID_TEXTURE_PATH / "up_tag.png").convert("RGBA")
        up_icon = up_icon.resize((68, 52))
        level_path = _XW_UID_TEXTURE_PATH.parent / "texture2d"
    else:
        item_fg = None
        up_icon = None
        level_path = None

    async def _draw_pic(item: Dict) -> Image.Image:
        """绘制单个五星卡片"""
        item_bg = Image.new("RGBA", (167, 170))
        if item_fg:
            item_fg_cp = item_fg.copy()
            item_bg.paste(item_fg_cp, (0, 0), item_fg_cp)

        item_temp = Image.new("RGBA", (167, 170))
        resource_id = item.get("resourceId", "")
        item_type = item.get("resourceType", "角色")

        try:
            if item_type == "武器":
                if _XW_UID_AVAILABLE:
                    item_icon = await get_square_weapon(resource_id)
                    item_icon = item_icon.resize((130, 130)).convert("RGBA")
                    item_temp.paste(item_icon, (22, 0), item_icon)
            else:
                if _XW_UID_AVAILABLE:
                    item_icon = await get_square_avatar(resource_id)
                    item_icon = await cropped_square_avatar(item_icon, 130)
                    item_temp.paste(item_icon, (22, 0), item_icon)
        except Exception:
            pass

        item_bg.paste(item_temp, (-2, -2), item_temp)

        gnum = item.get("gacha_num", 0)
        if gnum >= 70:
            gcolor = (230, 58, 58)
        elif gnum <= 40:
            gcolor = (43, 210, 43)
        else:
            gcolor = "white"

        info_block = Image.new("RGBA", (137, 28), color=(255, 255, 255, 0))
        info_block_draw = ImageDraw.Draw(info_block)
        info_block_draw.rectangle([0, 0, 137, 28], fill=(0, 0, 0, int(0.6 * 255)))
        if _XW_UID_AVAILABLE:
            info_block_draw.text((65, 12), f"{gnum}抽", gcolor, waves_font_20, "mm")
        else:
            info_block_draw.text((65, 12), f"{gnum}抽", gcolor, ImageFont.load_default(), "mm")
        item_bg.paste(info_block, (15, 130), info_block)

        if item.get("is_up") and up_icon:
            up_icon_cp = up_icon.copy()
            item_bg.paste(up_icon_cp, (88, 3), up_icon_cp)
        return item_bg

    y = 0
    gindex = 0

    POOL_DISPLAY_NAMES = {
        "limited_char": "限定角色调谐",
        "limited_weapon": "限定武器调谐",
        "standard_char": "角色常驻调谐",
        "standard_weapon": "武器常驻调谐",
    }

    for pool_type, gacha_data in pools_data.items():
        if not gacha_data["rank_s_list"]:
            gindex += 1
            continue

        title = Image.new("RGBA", (980, 250), (0, 0, 0, 0))
        if _XW_UID_AVAILABLE and (level_path / "bar.png").exists():
            title = Image.open(level_path / "bar.png").convert("RGBA")
        title_draw = ImageDraw.Draw(title)

        remain_s = f"{gacha_data['remain']}"
        avg_s = f"{gacha_data['avg']}"
        avg_up_s = f"{gacha_data['avg_up']}"
        total_s = f"{gacha_data['total']}"
        level = gacha_data["level"]

        pool_display_name = POOL_DISPLAY_NAMES.get(pool_type, pool_type)

        # 绘制标题栏信息
        if _XW_UID_AVAILABLE:
            title_draw.text((110, 80), pool_display_name, WHITE, waves_font_40, "lm")
            title_draw.text((160, 178), avg_s, WHITE, waves_font_32, "mm")
            title_draw.text((300, 178), avg_up_s, WHITE, waves_font_32, "mm")
            title_draw.text((457, 178), total_s, WHITE, waves_font_32, "mm")
            title_draw.text((380, 87), "已", WHITE, waves_font_23, "rm")
            title_draw.text((410, 84), remain_s, (255, 80, 80), waves_font_40, "mm")
            title_draw.text((530, 87), "抽未出金", WHITE, waves_font_23, "rm")

            # 等级图标
            lvl_dir = level_path / str(level)
            if lvl_dir.exists():
                level_files = list(lvl_dir.iterdir())
                if level_files:
                    level_icon = Image.open(random.choice(level_files)).convert("RGBA")
                    level_icon = level_icon.resize((140, 140)).convert("RGBA")
                    title.paste(level_icon, (710, 51), level_icon)
            tag = HOMO_TAG[level]
            title_draw.text((783, 225), tag, WHITE, waves_font_24, "mm")
        else:
            title_draw.text((50, 50), pool_display_name, WHITE, ImageFont.load_default(), "lm")
            title_draw.text((300, 120), f"均{avg_s}抽 UP均{avg_up_s} 总{total_s} 已{remain_s}抽未出金", WHITE, ImageFont.load_default(), "lm")

        card_img.paste(title, (10, _header + y + gindex * oset), title)
        gindex += 1

        s_list = gacha_data["rank_s_list"]
        s_list.reverse()

        for idx, item in enumerate(s_list):
            item_bg = await _draw_pic(item)
            _x = 95 + 162 * (idx % 5)
            _y = _header + bset * (idx // 5) + y + gindex * oset
            card_img.paste(item_bg, (_x, _y), item_bg)

        if s_list:
            y += bset * ((len(s_list) - 1) // 5 + 1)
        else:
            y += 50

    # 顶部标题区
    if _XW_UID_AVAILABLE:
        # 签名码标题
        title_layer = Image.new("RGBA", (1000, _header), (0, 0, 0, 0))
        title_draw = ImageDraw.Draw(title_layer)
        if signature_code:
            title_draw.text((500, 30), f"模拟抽卡记录  特征码: {signature_code}", GOLD, waves_font_30, "mm")
        else:
            title_draw.text((500, 30), "模拟抽卡记录", GOLD, waves_font_30, "mm")
        card_img.paste(title_layer, (0, 0), title_layer)

        # 总统计
        total_5star = len(records)
        total_pulls = sum(r.get("pity_count", 0) for r in records) or 0
        avg_pity = round(total_pulls / total_5star, 1) if total_5star > 0 else 0
        up_count = len([r for r in records if r.get("is_up", False)])
        stats_draw = ImageDraw.Draw(card_img)
        stats_draw.text(
            (970, _header - 60),
            f"五星:{total_5star}  均{avg_pity}抽  UP:{up_count}",
            GRAY, waves_font_20, "rm",
        )
    else:
        card_draw.text((500, 50), "模拟抽卡记录", GOLD, ImageFont.load_default(), "mm")

    if _XW_UID_AVAILABLE:
        card_img = add_footer(card_img, 600, 20)
        card_img = await convert_img(card_img)

    buf = BytesIO()
    card_img.save(buf, format="PNG", quality=95)
    return buf.getvalue()

