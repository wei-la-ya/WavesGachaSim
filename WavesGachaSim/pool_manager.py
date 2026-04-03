"""鸣潮抽卡模拟器 - 卡池管理"""
import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from gsuid_core.logger import logger
from gsuid_core.data_store import get_res_path

from .api import fetch_pool_list

try:
    from XutheringWavesUID.XutheringWavesUID.wutheringwaves_up.model import WavesPool
    from XutheringWavesUID.XutheringWavesUID.utils.name_convert import (
        easy_id_to_name,
        char_name_to_char_id,
        weapon_name_to_weapon_id,
    )
except ImportError as e:
    logger.warning(f"[模拟抽卡] 导入依赖失败: {e}")
    WavesPool = None
    easy_id_to_name = None
    char_name_to_char_id = None
    weapon_name_to_weapon_id = None

CONFIG_DIR = Path(__file__).parent / "config"

# 卡池数据持久化路径
POOL_DATA_DIR = get_res_path() / "WavesGachaSim"
POOL_DATA_DIR.mkdir(parents=True, exist_ok=True)
POOL_CACHE_FILE = POOL_DATA_DIR / "cached_pools.json"

# 常驻5星角色 (用于限定角色池歪的情况)
STANDARD_5STAR_CHARACTERS = ["鉴心", "卡卡罗", "维里奈", "凌阳", "安可"]


class PoolManager:
    """卡池管理器"""

    def __init__(self):
        self._standard_pools: Optional[Dict] = None
        self._weapons_3star: Optional[List[str]] = None
        self._cached_limited_pools: Optional[List[Dict]] = None
        self._cache_date: str = ""
        self._fetch_lock: Union[asyncio.Lock, None] = None  # 并发保护锁
        # 启动时从本地 JSON 加载上次缓存
        self._load_pool_cache()

    def _get_fetch_lock(self) -> asyncio.Lock:
        """获取或创建 fetch 锁"""
        if self._fetch_lock is None:
            self._fetch_lock = asyncio.Lock()
        return self._fetch_lock

    # ─── 卡池数据持久化 ───

    def _load_pool_cache(self) -> None:
        """从本地 JSON 文件加载卡池缓存"""
        if POOL_CACHE_FILE.exists():
            try:
                with open(POOL_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._cached_limited_pools = data.get("pools", [])
                self._cache_date = data.get("date", "")
                logger.info(
                    f"[模拟抽卡] 从本地缓存加载 {len(self._cached_limited_pools)} 个卡池 "
                    f"(缓存日期: {self._cache_date})"
                )
            except Exception as e:
                logger.warning(f"[模拟抽卡] 加载本地卡池缓存失败: {e}")

    def _save_pool_cache(self) -> None:
        """将卡池数据保存到本地 JSON 文件"""
        if self._cached_limited_pools is not None:
            try:
                data = {
                    "date": self._cache_date,
                    "pools": self._cached_limited_pools,
                }
                with open(POOL_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"[模拟抽卡] 卡池数据已保存到 {POOL_CACHE_FILE}"
                )
            except Exception as e:
                logger.warning(f"[模拟抽卡] 保存卡池缓存失败: {e}")

    # ─── 配置文件加载 ───

    def _load_standard_pools(self) -> Dict:
        if self._standard_pools is None:
            fp = CONFIG_DIR / "standard_pools.json"
            if fp.exists():
                with open(fp, "r", encoding="utf-8") as f:
                    self._standard_pools = json.load(f)
            else:
                self._standard_pools = {}
        return self._standard_pools

    def _load_3star_weapons(self) -> List[str]:
        if self._weapons_3star is None:
            fp = CONFIG_DIR / "weapons_3star.json"
            if fp.exists():
                with open(fp, "r", encoding="utf-8") as f:
                    self._weapons_3star = json.load(f)
            else:
                self._weapons_3star = []
        return self._weapons_3star

    def get_3star_weapons(self) -> List[str]:
        return self._load_3star_weapons()

    # ─── API 获取限定卡池 ───

    async def fetch_current_pools(self, force: bool = False) -> List[Dict]:
        """
        从 API 获取当前活跃卡池并转换为统一格式。
        结果缓存一天，每天只获取一次。
        使用锁防止多个请求同时发起 API 调用。
        """
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        
        # 非强制刷新时，先检查缓存
        if not force and self._cached_limited_pools is not None and self._cache_date == today:
            return self._cached_limited_pools
        
        # 使用锁防止并发请求
        async with self._get_fetch_lock():
            # 双重检查：获取锁后再次检查缓存（可能其他协程已更新）
            if not force and self._cached_limited_pools is not None and self._cache_date == today:
                return self._cached_limited_pools
            
            api_pools = await fetch_pool_list()
            if api_pools is None:
                return self._cached_limited_pools or []

            pools: List[Dict] = []
            weapons_3star = self._load_3star_weapons()

        for raw in api_pools:
            try:
                wp = WavesPool.model_validate(raw) if WavesPool else None
            except Exception:
                wp = None

            if wp is None:
                continue

            # 判断类型
            if wp.pool_type == "角色活动唤取":
                ptype = "limited_char"
            elif wp.pool_type == "武器活动唤取":
                ptype = "limited_weapon"
            else:
                continue

            # 构造 UP 5星列表
            up5: List[Dict] = []
            for fid, fname in zip(wp.five_star_ids, wp.five_star_names):
                item_type = "weapon" if ptype == "limited_weapon" else "character"
                up5.append({"name": fname, "type": item_type, "resource_id": fid})

            # 构造 UP 4星列表
            up4: List[Dict] = []
            for fid, fname in zip(wp.four_star_ids, wp.four_star_names):
                # 4星可能混有角色和武器，通过 id 前缀判断
                # 角色 id 一般 1xxx，武器 id 一般 2xxxx
                item_type = "weapon" if fid.startswith("2") else "character"
                up4.append({"name": fname, "type": item_type, "resource_id": fid})

            # 常驻5星 (歪的时候出的)
            std5: List[Dict] = []
            if ptype == "limited_char":
                for name in STANDARD_5STAR_CHARACTERS:
                    rid = ""
                    if char_name_to_char_id:
                        rid = char_name_to_char_id(name) or ""
                    std5.append({"name": name, "type": "character", "resource_id": rid})

            # 常驻4星直接复用配置
            std_pools = self._load_standard_pools()
            if ptype == "limited_char":
                sp = std_pools.get("character", {})
            else:
                sp = std_pools.get("weapon", {})

            std4: List[Dict] = []
            for n in sp.get("4star_characters", []):
                rid = ""
                if char_name_to_char_id:
                    rid = char_name_to_char_id(n) or ""
                std4.append({"name": n, "type": "character", "resource_id": rid})
            for n in sp.get("4star_weapons", []):
                rid = ""
                if weapon_name_to_weapon_id:
                    rid = weapon_name_to_weapon_id(n) or ""
                std4.append({"name": n, "type": "weapon", "resource_id": rid})

            # 构造卡池名称：如果 wp.name 为空，用 UP 五星角色/武器名代替
            display_name = wp.name
            if not display_name and wp.five_star_names:
                display_name = "、".join(wp.five_star_names)

            pool_id = f"{ptype}_{display_name or wp.title}"
            pool_dict: Dict[str, Any] = {
                "id": pool_id,
                "name": f"{display_name} · {wp.title}" if display_name else wp.title,
                "type": ptype,
                "startTime": wp.start_time,
                "endTime": wp.end_time,
                "up": {"5star": up5, "4star": up4},
                "standard5star": std5,
                "standard4star": std4,
                "3star_weapons": weapons_3star,
                "pic": wp.pic,
            }
            pools.append(pool_dict)

        self._cached_limited_pools = pools
        self._cache_date = today
        self._save_pool_cache()
        logger.info(f"[模拟抽卡] 获取到 {len(pools)} 个限定卡池")
        return pools

    async def get_current_limited_char_pools(self) -> List[Dict]:
        pools = await self.fetch_current_pools()
        now = datetime.now()
        result = []
        for p in pools:
            if p["type"] != "limited_char":
                continue
            try:
                end = datetime.strptime(p["endTime"], "%Y-%m-%d %H:%M:%S")
                if now > end:
                    continue
            except Exception:
                pass
            result.append(p)
        return result

    async def get_current_limited_weapon_pools(self) -> List[Dict]:
        pools = await self.fetch_current_pools()
        now = datetime.now()
        result = []
        for p in pools:
            if p["type"] != "limited_weapon":
                continue
            try:
                end = datetime.strptime(p["endTime"], "%Y-%m-%d %H:%M:%S")
                if now > end:
                    continue
            except Exception:
                pass
            result.append(p)
        return result

    # ─── 常驻池 ───

    def get_standard_char_pool(self) -> Dict[str, Any]:
        sp = self._load_standard_pools().get("character", {})
        weapons_3star = self._load_3star_weapons()

        std5 = [{"name": n, "type": "character", "resource_id": ""} for n in sp.get("5star", [])]
        std4_c = [{"name": n, "type": "character", "resource_id": ""} for n in sp.get("4star_characters", [])]
        std4_w = [{"name": n, "type": "weapon", "resource_id": ""} for n in sp.get("4star_weapons", [])]

        return {
            "id": "standard_char",
            "name": "常规唤取（角色）",
            "type": "standard_char",
            "up": {"5star": [], "4star": []},
            "standard5star": std5,
            "standard4star": std4_c + std4_w,
            "3star_weapons": weapons_3star,
        }

    def get_standard_weapon_pool(self) -> Dict[str, Any]:
        sp = self._load_standard_pools().get("weapon", {})
        weapons_3star = self._load_3star_weapons()

        std5 = [{"name": n, "type": "weapon", "resource_id": ""} for n in sp.get("5star", [])]
        std4_w = [{"name": n, "type": "weapon", "resource_id": ""} for n in sp.get("4star_weapons", [])]
        std4_c = [{"name": n, "type": "character", "resource_id": ""} for n in sp.get("4star_characters", [])]

        return {
            "id": "standard_weapon",
            "name": "常规唤取（武器）",
            "type": "standard_weapon",
            "up": {"5star": [], "4star": []},
            "standard5star": std5,
            "standard4star": std4_w + std4_c,
            "3star_weapons": weapons_3star,
        }

    async def get_pool_by_id(self, pool_id: str) -> Optional[Dict]:
        if pool_id == "standard_char":
            return self.get_standard_char_pool()
        if pool_id == "standard_weapon":
            return self.get_standard_weapon_pool()
        pools = await self.fetch_current_pools()
        for p in pools:
            if p["id"] == pool_id:
                return p
        return None

    # ─── 便捷方法 ───

    async def get_limited_char_pools(self) -> List[Dict]:
        return await self.get_current_limited_char_pools()

    async def get_limited_weapon_pools(self) -> List[Dict]:
        return await self.get_current_limited_weapon_pools()

    async def get_first_limited_char_pool(self) -> Optional[Dict]:
        pools = await self.get_current_limited_char_pools()
        return pools[0] if pools else None

    async def get_first_limited_weapon_pool(self) -> Optional[Dict]:
        pools = await self.get_current_limited_weapon_pools()
        return pools[0] if pools else None


# 全局实例
pool_manager = PoolManager()
