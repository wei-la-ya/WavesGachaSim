"""init"""
from gsuid_core.sv import Plugins

Plugins(name="WavesGachaSim", force_prefix=["ww"], allow_empty_prefix=False)

"""鸣潮抽卡模拟器 - 命令注册"""

import asyncio

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from .gacha_service import gacha_service
from .gacha_sim_config import GachaSimConfig
from .pool_manager import pool_manager
from .data_manager import data_manager
from .draw_gacha_result import render_gacha_result, format_text_result, render_pool_select

sv_gacha = SV("模拟抽卡")

# 每用户锁，防止同一用户并发抽卡导致保底数据竞态
# 使用 LRU 策略：锁释放后如果没有其他等待者就删除，避免内存泄漏
_user_locks: dict[str, asyncio.Lock] = {}
_user_lock_waits: dict[str, int] = {}  # 记录每个锁的等待者数量


def _get_user_lock(uid: str) -> asyncio.Lock:
    """获取用户的锁，如果不存在则创建"""
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


async def _release_user_lock(uid: str) -> None:
    """释放锁后检查是否需要清理"""
    # 检查是否还有其他等待者
    wait_count = _user_lock_waits.get(uid, 0)
    if wait_count <= 0 and uid in _user_locks:
        # 没有等待者了，删除锁释放内存
        del _user_locks[uid]
        if uid in _user_lock_waits:
            del _user_lock_waits[uid]


class _UserLockContext:
    """用户锁上下文管理器，支持 LRU 清理"""
    
    def __init__(self, uid: str):
        self.uid = uid
        self.lock = _get_user_lock(uid)
    
    async def __aenter__(self):
        # 增加等待计数
        _user_lock_waits[self.uid] = _user_lock_waits.get(self.uid, 0) + 1
        await self.lock.acquire()
        return self.lock
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.lock.release()
        # 减少等待计数
        _user_lock_waits[self.uid] = _user_lock_waits.get(self.uid, 1) - 1
        # 检查是否需要清理
        await _release_user_lock(self.uid)


async def _get_available_pools(pool_type: str) -> list:
    """
    根据配置获取可用卡池列表。
    
    - 跟随接口 模式: 返回当期所有API卡池
    - 手动指定 模式: 返回管理员指定的卡池 + 当期UP卡池（去重）
    """
    await pool_manager.fetch_current_pools()
    
    pool_mode = GachaSimConfig.get_config("GachaSimPoolMode").data
    
    # 获取当期卡池
    if pool_type == "limited_char":
        current_pools = await pool_manager.get_limited_char_pools()
    elif pool_type == "limited_weapon":
        current_pools = await pool_manager.get_limited_weapon_pools()
    else:
        return []
    
    if pool_mode == "跟随接口":
        return current_pools
    
    # 手动指定 模式
    manual_names = []
    for key in ("GachaSimManualPool1", "GachaSimManualPool2", "GachaSimManualPool3"):
        name = GachaSimConfig.get_config(key).data
        if name and name.strip():
            manual_names.append(name.strip())
    
    if not manual_names:
        # 没配置手动卡池，自动使用当期UP角色
        char_pools = current_pools if pool_type == "limited_char" else await pool_manager.get_limited_char_pools()
        for pool in char_pools:
            for item in pool.get("up", {}).get("5star", []):
                if item["name"] not in manual_names:
                    manual_names.append(item["name"])
        if not manual_names:
            return current_pools
    
    # 根据角色名匹配卡池
    matched_pools = []
    matched_ids = set()
    
    if pool_type == "limited_char":
        # 角色池直接按配置的角色名匹配
        for pool in current_pools:
            up5_names = [item["name"] for item in pool.get("up", {}).get("5star", [])]
            for manual_name in manual_names:
                if manual_name in up5_names and pool["id"] not in matched_ids:
                    matched_pools.append(pool)
                    matched_ids.add(pool["id"])
    elif pool_type == "limited_weapon":
        # 武器池：通过角色卡池的时间范围匹配同期武器池
        # 先找到匹配的角色卡池时间
        char_pools = await pool_manager.get_limited_char_pools()
        matched_time_ranges = []
        for pool in char_pools:
            up5_names = [item["name"] for item in pool.get("up", {}).get("5star", [])]
            for manual_name in manual_names:
                if manual_name in up5_names:
                    matched_time_ranges.append((pool.get("startTime", ""), pool.get("endTime", "")))
        
        # 找同期的武器池
        for pool in current_pools:
            pool_start = pool.get("startTime", "")
            pool_end = pool.get("endTime", "")
            for start, end in matched_time_ranges:
                # 时间有重叠就认为是同期
                if pool_start == start or pool_end == end:
                    if pool["id"] not in matched_ids:
                        matched_pools.append(pool)
                        matched_ids.add(pool["id"])
    
    return matched_pools if matched_pools else current_pools


async def _update_pool_options():
    """
    动态更新手动卡池配置的 options 列表。
    从当期卡池中提取所有UP角色名，填入配置选项供 web 管理后台下拉选择。
    """
    try:
        await pool_manager.fetch_current_pools()
        char_pools = await pool_manager.get_limited_char_pools()
        up_names = [""]  # 空选项 = 不启用
        for pool in char_pools:
            for item in pool.get("up", {}).get("5star", []):
                name = item.get("name", "")
                if name and name not in up_names:
                    up_names.append(name)

        # 更新配置项的 options
        for key in ("GachaSimManualPool1", "GachaSimManualPool2", "GachaSimManualPool3"):
            cfg = GachaSimConfig.get_config(key)
            if hasattr(cfg, "options"):
                cfg.options = up_names
    except Exception:
        pass


# 启动时更新卡池选项列表（供web管理后台下拉选择）
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.call_later(3.0, lambda: asyncio.create_task(_update_pool_options()))
    else:
        asyncio.run(_update_pool_options())
except Exception:
    pass


async def _do_draw(
    bot: Bot,
    ev: Event,
    pool_type: str,
    count: int,
    get_pool_func,
):
    """通用的抽卡处理函数"""
    uid = ev.user_id

    # 检查功能总开关
    if not GachaSimConfig.get_config("GachaSimEnabled").data:
        at_sender = True if ev.group_id else False
        await bot.send("模拟抽卡功能已关闭", at_sender)
        return

    # 同一用户加锁，防止并发竞态（使用 LRU 上下文管理器）
    async with _UserLockContext(uid):
        # 获取每日限制配置
        daily_limit = GachaSimConfig.get_config("GachaSimDailyLimit").data

        # 检查每日限制
        daily_count = await data_manager.get_daily_count(uid, pool_type)

        # 检查主人是否无限抽取
        master_unlimited = GachaSimConfig.get_config("GachaSimMasterUnlimited").data
        if master_unlimited and ev.user_pm is not None and ev.user_pm <= 1:
            pass
        elif daily_limit > 0 and daily_count >= daily_limit:
            at_sender = True if ev.group_id else False
            msg = f"今日该池已抽{daily_count}次，已达上限{daily_limit}次"
            await bot.send(msg, at_sender)
            return

        # 获取卡池
        await pool_manager.fetch_current_pools()

        # 获取用户选择的卡池
        selected_pool_id = await data_manager.get_selected_pool(uid, pool_type)

        # 根据 pool_type 获取可用池子列表
        user_switch_all = GachaSimConfig.get_config("GachaSimUserSwitchAll").data
        if pool_type == "limited_char":
            if user_switch_all:
                available_pools = await pool_manager.get_limited_char_pools()
            else:
                available_pools = await _get_available_pools("limited_char")
        elif pool_type == "limited_weapon":
            if user_switch_all:
                available_pools = await pool_manager.get_limited_weapon_pools()
            else:
                available_pools = await _get_available_pools("limited_weapon")
        elif pool_type == "standard_char":
            available_pools = [pool_manager.get_standard_char_pool()]
        elif pool_type == "standard_weapon":
            available_pools = [pool_manager.get_standard_weapon_pool()]
        else:
            available_pools = []

        if not available_pools:
            at_sender = True if ev.group_id else False
            await bot.send("当前没有可用的卡池，请稍后再试~", at_sender)
            return

        # 检查用户选择是否有效
        pool = None
        if selected_pool_id:
            for p in available_pools:
                if p.get("id") == selected_pool_id:
                    pool = p
                    break
            # 如果选择的卡池已过期或不在可用列表中，清除选择
            if not pool:
                await data_manager.set_selected_pool(uid, pool_type, "")
                selected_pool_id = ""

        # 多卡池时未选择 → 提示用户选择（图片渲染）
        if not pool and len(available_pools) > 1 and pool_type in ("limited_char", "limited_weapon"):
            # 按类型分开
            char_pools_show = [p for p in available_pools if p.get("type") == "limited_char"]
            weapon_pools_show = [p for p in available_pools if p.get("type") == "limited_weapon"]
            
            # 如果当前抽的是角色池，也顺便展示武器池
            if pool_type == "limited_char" and not weapon_pools_show:
                weapon_pools_show = await _get_available_pools("limited_weapon")
            elif pool_type == "limited_weapon" and not char_pools_show:
                char_pools_show = await _get_available_pools("limited_char")

            img = await render_pool_select(
                char_pools=char_pools_show,
                weapon_pools=weapon_pools_show,
                start_index=1,
            )

            if img:
                await bot.send(MessageSegment.image(img))
            else:
                # 回退文本
                pool_list = "当前有多个卡池可选：\n\n"
                for i, p in enumerate(available_pools, 1):
                    up5_names = [item["name"] for item in p.get("up", {}).get("5star", [])]
                    pool_list += f"{i}. {p.get('name', '未知')} (UP: {'、'.join(up5_names)})\n"
                pool_list += "\n请使用 `ww切换卡池 + 编号` 选择卡池后再抽卡~"
                at_sender = True if ev.group_id else False
                await bot.send(pool_list, at_sender)
            return

        # 只有一个卡池时自动使用
        if not pool:
            pool = available_pools[0]

        # 保留原有逻辑：没池子时调用 get_pool_func 作为兜底
        if not pool:
            result = get_pool_func()
            if hasattr(result, '__await__'):
                pool = await result
            else:
                pool = result

        if not pool:
            at_sender = True if ev.group_id else False
            msg = "未能获取到有效卡池，请稍后再试~"
            await bot.send(msg, at_sender)
            return

        # 获取保底数据
        pity_data = await data_manager.get_pity_data(uid, pool_type)

        # 执行抽卡
        results = gacha_service.perform_draw(
            pool,
            pity_data,
            pool_manager.get_3star_weapons(),
            count=count,
        )

        # 保存保底数据
        await data_manager.save_pity_data(uid, pool_type, pity_data)

        # 更新每日计数
        await data_manager.add_daily_count(uid, pool_type, count)

        # 记录5星历史
        for item in results:
            if item.get("star") == 5:
                item["pool_type"] = pool_type
                await data_manager.add_five_star_record(uid, ev.bot_id, item)

        # 获取用户特征码（首次抽卡自动生成）
        signature_code = await data_manager.get_signature(uid)
        if not signature_code:
            signature_code = await data_manager.generate_signature(uid)

        # 渲染图片结果（不显示保底信息）
        img = await render_gacha_result(
            results,
            pool.get("name", "未知卡池"),
            signature_code=signature_code,
            draw_type=count,
            nickname=ev.sender.get('nickname', '') if ev.sender else '',
        )

        # 检查文本回退配置
        text_fallback = GachaSimConfig.get_config("GachaSimTextFallback").data
        if img:
            await bot.send(MessageSegment.image(img))
        elif text_fallback:
            text_result = format_text_result(
                results,
                pool.get("name", "未知卡池"),
                signature_code,
            )
            at_sender = True if ev.group_id else False
            await bot.send(text_result, at_sender)
        else:
            at_sender = True if ev.group_id else False
            await bot.send("图片渲染失败", at_sender)


# ==================== 帮助命令 ====================
@sv_gacha.on_fullmatch(("抽卡帮助",), block=True)
async def send_gacha_help(bot: Bot, ev: Event):
    """发送抽卡帮助信息"""
    daily_limit = GachaSimConfig.get_config("GachaSimDailyLimit").data
    help_text = f"""**鸣潮模拟抽卡帮助**

=== 限定角色 ===
- `ww抽卡` - 限定角色UP十连

=== 限定武器 ===
- `ww抽卡武器` - 限定武器UP十连

=== 常驻角色 ===
- `ww抽卡常驻` - 常驻角色十连

=== 常驻武器 ===
- `ww抽卡常驻武器` - 常驻武器十连

=== 其他命令 ===
- `ww切换卡池` - 切换限定角色池（输入编号或名称）
- `ww切换武器卡池` - 切换限定武器池（输入编号或名称）
- `ww卡池状态` - 查看当前保底状态
- `ww抽卡统计` - 查看5星历史记录
- `ww抽卡概率` - 查看概率说明
- `ww更新卡池` - 强制从API获取最新卡池
- `ww模拟绑定123456789` - 绑定9位特征码
- `ww抽卡帮助` - 查看本帮助

**每日抽卡上限: {daily_limit}次**"""

    at_sender = True if ev.group_id else False
    await bot.send(help_text, at_sender)


# ==================== 限定角色抽卡 ====================
@sv_gacha.on_fullmatch(("抽卡",), block=True)
async def draw_limited_char_10(bot: Bot, ev: Event):
    """限定角色十连抽"""
    await _do_draw(
        bot,
        ev,
        "limited_char",
        10,
        pool_manager.get_first_limited_char_pool,
    )


# ==================== 限定武器抽卡 ====================
@sv_gacha.on_fullmatch(("抽卡武器",), block=True)
async def draw_limited_weapon_10(bot: Bot, ev: Event):
    """限定武器十连抽"""
    await _do_draw(
        bot,
        ev,
        "limited_weapon",
        10,
        pool_manager.get_first_limited_weapon_pool,
    )


# ==================== 常驻角色抽卡 ====================
@sv_gacha.on_fullmatch(("抽卡常驻",), block=True)
async def draw_standard_char_10(bot: Bot, ev: Event):
    """常驻角色十连抽"""
    await _do_draw(
        bot,
        ev,
        "standard_char",
        10,
        pool_manager.get_standard_char_pool,
    )


# ==================== 常驻武器抽卡 ====================
@sv_gacha.on_fullmatch(("抽卡常驻武器",), block=True)
async def draw_standard_weapon_10(bot: Bot, ev: Event):
    """常驻武器十连抽"""
    await _do_draw(
        bot,
        ev,
        "standard_weapon",
        10,
        pool_manager.get_standard_weapon_pool,
    )


# ==================== 切换卡池 ====================
@sv_gacha.on_command(("切换卡池",), block=True)
async def switch_pool(bot: Bot, ev: Event):
    """切换角色卡池"""
    uid = ev.user_id
    user_input = ev.text.strip() if ev.text else ""

    await pool_manager.fetch_current_pools()

    # 获取配置
    user_switch_all = GachaSimConfig.get_config("GachaSimUserSwitchAll").data

    if user_switch_all:
        limited_char_pools = await pool_manager.get_limited_char_pools()
    else:
        limited_char_pools = await _get_available_pools("limited_char")

    at_sender = True if ev.group_id else False

    # 用户未输入参数，列出角色卡池（图片渲染）
    if not user_input:
        if not limited_char_pools:
            msg = "当前没有可用的角色限定卡池~"
            await bot.send(msg, at_sender)
            return

        current_char = await data_manager.get_selected_pool(uid, "limited_char")

        img = await render_pool_select(
            char_pools=limited_char_pools,
            weapon_pools=[],
            selected_char_id=current_char or "",
            selected_weapon_id="",
            start_index=1,
        )

        if img:
            await bot.send(MessageSegment.image(img))
        else:
            pool_list_text = "**可选角色卡池列表：**\n\n"
            for i, p in enumerate(limited_char_pools, 1):
                pool_list_text += f"{i}. {p.get('name', '未知')}\n"
            pool_list_text += "\n请回复 `ww切换卡池 + 编号` 或 `ww切换卡池 + 名称` 来选择角色卡池~"
            if current_char:
                for p in limited_char_pools:
                    if p.get("id") == current_char:
                        pool_list_text += f"\n\n**当前选择：** {p.get('name')}"
                        break
            await bot.send(pool_list_text, at_sender)
        return

    # 用户输入了参数，尝试匹配
    selected_pool = None
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(limited_char_pools):
            selected_pool = limited_char_pools[idx - 1].get("id")
    else:
        for p in limited_char_pools:
            if user_input in p.get("name", ""):
                selected_pool = p.get("id")
                break

    if selected_pool:
        await data_manager.set_selected_pool(uid, "limited_char", selected_pool)
        pool_name = ""
        for p in limited_char_pools:
            if p.get("id") == selected_pool:
                pool_name = p.get("name")
                break
        msg = f"已切换到 [限定角色] {pool_name}~"
        await bot.send(msg, at_sender)
    else:
        msg = f"未找到匹配 '{user_input}' 的角色卡池，请检查后重试~"
        await bot.send(msg, at_sender)


@sv_gacha.on_command(("切换武器卡池",), block=True)
async def switch_weapon_pool(bot: Bot, ev: Event):
    """切换武器卡池"""
    uid = ev.user_id
    user_input = ev.text.strip() if ev.text else ""

    await pool_manager.fetch_current_pools()

    user_switch_all = GachaSimConfig.get_config("GachaSimUserSwitchAll").data

    if user_switch_all:
        limited_weapon_pools = await pool_manager.get_limited_weapon_pools()
    else:
        limited_weapon_pools = await _get_available_pools("limited_weapon")

    at_sender = True if ev.group_id else False

    # 用户未输入参数，列出武器卡池（图片渲染）
    if not user_input:
        if not limited_weapon_pools:
            msg = "当前没有可用的武器限定卡池~"
            await bot.send(msg, at_sender)
            return

        current_weapon = await data_manager.get_selected_pool(uid, "limited_weapon")

        img = await render_pool_select(
            char_pools=[],
            weapon_pools=limited_weapon_pools,
            selected_char_id="",
            selected_weapon_id=current_weapon or "",
            start_index=1,
        )

        if img:
            await bot.send(MessageSegment.image(img))
        else:
            pool_list_text = "**可选武器卡池列表：**\n\n"
            for i, p in enumerate(limited_weapon_pools, 1):
                pool_list_text += f"{i}. {p.get('name', '未知')}\n"
            pool_list_text += "\n请回复 `ww切换武器卡池 + 编号` 或 `ww切换武器卡池 + 名称` 来选择武器卡池~"
            if current_weapon:
                for p in limited_weapon_pools:
                    if p.get("id") == current_weapon:
                        pool_list_text += f"\n\n**当前选择：** {p.get('name')}"
                        break
            await bot.send(pool_list_text, at_sender)
        return

    # 用户输入了参数，尝试匹配
    selected_pool = None
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(limited_weapon_pools):
            selected_pool = limited_weapon_pools[idx - 1].get("id")
    else:
        for p in limited_weapon_pools:
            if user_input in p.get("name", ""):
                selected_pool = p.get("id")
                break

    if selected_pool:
        await data_manager.set_selected_pool(uid, "limited_weapon", selected_pool)
        pool_name = ""
        for p in limited_weapon_pools:
            if p.get("id") == selected_pool:
                pool_name = p.get("name")
                break
        msg = f"已切换到 [限定武器] {pool_name}~"
        await bot.send(msg, at_sender)
    else:
        msg = f"未找到匹配 '{user_input}' 的武器卡池，请检查后重试~"
        await bot.send(msg, at_sender)


# ==================== 卡池状态 ====================
@sv_gacha.on_fullmatch(("卡池状态",), block=True)
async def show_pool_status(bot: Bot, ev: Event):
    """显示卡池保底状态"""
    uid = ev.user_id

    status_text = "**当前保底状态**\n\n"

    # 限定角色
    pity_char = await data_manager.get_pity_data(uid, "limited_char")
    status_text += "【限定角色】\n"
    status_text += f"  累计抽数: {pity_char.get('current_count', 0)}\n"
    status_text += f"  已触发保底: {'是' if pity_char.get('guaranteed5', False) else '否'}\n"
    status_text += f"  总抽数: {pity_char.get('total_count', 0)}\n\n"

    # 限定武器
    pity_weapon = await data_manager.get_pity_data(uid, "limited_weapon")
    status_text += "【限定武器】\n"
    status_text += f"  累计抽数: {pity_weapon.get('current_count', 0)}\n"
    status_text += f"  已触发保底: {'是' if pity_weapon.get('guaranteed5', False) else '否'}\n"
    status_text += f"  总抽数: {pity_weapon.get('total_count', 0)}\n\n"

    # 常驻角色
    pity_std_char = await data_manager.get_pity_data(uid, "standard_char")
    status_text += "【常驻角色】\n"
    status_text += f"  累计抽数: {pity_std_char.get('current_count', 0)}\n"
    status_text += f"  已触发保底: {'是' if pity_std_char.get('guaranteed5', False) else '否'}\n"
    status_text += f"  总抽数: {pity_std_char.get('total_count', 0)}\n\n"

    # 常驻武器
    pity_std_weapon = await data_manager.get_pity_data(uid, "standard_weapon")
    status_text += "【常驻武器】\n"
    status_text += f"  累计抽数: {pity_std_weapon.get('current_count', 0)}\n"
    status_text += f"  已触发保底: {'是' if pity_std_weapon.get('guaranteed5', False) else '否'}\n"
    status_text += f"  总抽数: {pity_std_weapon.get('total_count', 0)}"

    at_sender = True if ev.group_id else False
    await bot.send(status_text, at_sender)


# ==================== 统计 ====================
@sv_gacha.on_fullmatch(("抽卡统计",), block=True)
async def show_statistics(bot: Bot, ev: Event):
    """显示5星历史记录"""
    uid = ev.user_id

    history = await data_manager.get_five_star_history(uid)

    if not history:
        msg = "暂无5星记录，快去抽卡吧~"
    else:
        msg = f"**5星历史记录** (共 {len(history)} 次)\n\n"
        # 显示最近10条
        recent = history[-10:] if len(history) > 10 else history
        for i, item in enumerate(recent, 1):
            name = item.get("name", "未知")
            star = item.get("star", 5)
            msg += f"{i}. ★{star} {name}\n"

        if len(history) > 10:
            msg += f"\n... 还有 {len(history) - 10} 条更早的记录"

    at_sender = True if ev.group_id else False
    await bot.send(msg, at_sender)


# ==================== 概率说明 ====================
@sv_gacha.on_fullmatch(("抽卡概率",), block=True)
async def show_rates(bot: Bot, ev: Event):
    """显示概率说明"""
    rates_text = """**鸣潮抽卡概率**

=== 5星概率 ===
- 基础概率: 0.8%
- 60抽未出后开始累积概率
- 第66-70抽: 每抽 +4%
- 第71-75抽: 每抽 +8%
- 第76-78抽: 每抽 +10%
- **第79抽: 必出5星!**

=== 4星概率 ===
- 基础概率: 2.66% (含4星武器)
- 10抽未出后开始累积
- 每抽 +3%

=== 3星概率 ===
- 基础概率: 96.54%
- 武器池为100%

祝各位抽卡顺利!"""

    at_sender = True if ev.group_id else False
    await bot.send(rates_text, at_sender)


# ==================== 更新卡池 ====================
@sv_gacha.on_command(("更新卡池",), block=True)
async def update_pools(bot: Bot, ev: Event):
    """强制从API获取最新卡池"""
    at_sender = True if ev.group_id else False
    msg = "正在从API获取最新卡池数据..."
    await bot.send(msg, at_sender)

    try:
        pools = await pool_manager.fetch_current_pools(force=True)
        if pools:
            await _update_pool_options()
            msg = f"✅ 卡池更新成功！当前共有 {len(pools)} 个限定卡池"
        else:
            msg = "⚠️ 未能获取到新卡池（可能API暂时不可用），已使用缓存数据"
    except Exception as e:
        msg = f"❌ 更新卡池失败: {e}"

    await bot.send(msg, at_sender)


# ==================== 绑定特征码 ====================
@sv_gacha.on_command(("模拟绑定",), block=True)
async def bind_signature(bot: Bot, ev: Event):
    """绑定用户特征码"""
    uid = ev.user_id
    user_input = (ev.text or "").strip()
    at_sender = True if ev.group_id else False

    if not user_input:
        # 显示当前特征码
        current_code = await data_manager.get_signature(uid)
        if current_code:
            msg = f"你的当前特征码: **{current_code}**\n\n如需更换，请回复 `ww模拟绑定123456789`"
        else:
            msg = "你还没有特征码，首次抽卡时会自动生成~\n\n如需手动生成，请回复 `ww模拟绑定123456789`"
        await bot.send(msg, at_sender)
        return

    # 验证特征码格式（9位数字）
    if not user_input.isdigit() or len(user_input) != 9:
        msg = "❌ 特征码必须是9位数字！"
        await bot.send(msg, at_sender)
        return

    # 检查特征码是否已被使用
    if await data_manager.check_code_exists(user_input):
        # 检查是否是自己正在绑定自己的码
        current = await data_manager.get_signature(uid)
        if current == user_input:
            msg = f"这个特征码已经是你的了，当前特征码: **{user_input}**"
        else:
            msg = "❌ 该特征码已被其他用户绑定，请更换一个~"
        await bot.send(msg, at_sender)
        return

    # 绑定特征码
    await data_manager.set_signature(uid, user_input)
    msg = f"✅ 特征码绑定成功！\n你的特征码: **{user_input}**"
    await bot.send(msg, at_sender)
