"""鸣潮抽卡模拟器 - 数据管理 (SQLite)"""
import random
from typing import Any, Dict, List, Optional

from gsuid_core.logger import logger
from .models import GachaSimPity, GachaSimRecord, GachaSimPool, GachaSimDaily, GachaSimSignature


class DataManager:
    """数据管理器 - 封装数据库操作"""

    async def get_pity_data(self, user_id: str, pool_type: str) -> Dict[str, Any]:
        """获取保底数据，返回字典格式（兼容 gacha_service）"""
        pity = await GachaSimPity.get_pity(user_id, pool_type)
        if pity:
            return {
                "current_count": pity.current_count,
                "pity4": pity.pity4,
                "guaranteed5": pity.guaranteed5,
                "guaranteed4": pity.guaranteed4,
                "total_count": pity.total_count,
            }
        return {
            "current_count": 0,
            "pity4": 0,
            "guaranteed5": False,
            "guaranteed4": False,
            "total_count": 0,
        }

    async def save_pity_data(self, user_id: str, pool_type: str, pity_data: Dict) -> None:
        """保存保底数据"""
        await GachaSimPity.save_pity(
            user_id, pool_type,
            pity_data.get("current_count", 0),
            pity_data.get("pity4", 0),
            pity_data.get("guaranteed5", False),
            pity_data.get("guaranteed4", False),
            pity_data.get("total_count", 0),
        )

    async def get_daily_count(self, user_id: str, pool_type: str) -> int:
        return await GachaSimDaily.get_daily_count(user_id, pool_type)

    async def add_daily_count(self, user_id: str, pool_type: str, count: int) -> None:
        await GachaSimDaily.add_daily_count(user_id, pool_type, count)

    async def get_selected_pool(self, user_id: str, pool_type: str) -> Optional[str]:
        return await GachaSimPool.get_selected(user_id, pool_type)

    async def set_selected_pool(self, user_id: str, pool_type: str, pool_id: str) -> None:
        await GachaSimPool.set_selected(user_id, pool_type, pool_id)

    async def add_five_star_record(self, user_id: str, bot_id: str, item: Dict) -> None:
        await GachaSimRecord.add_record(
            user_id, bot_id,
            item.get("pool_type", ""),
            item["name"],
            item["star"],
            item.get("type", "character"),
            item.get("is_up", False),
            item.get("pity_count", 0),
        )

    async def get_five_star_history(self, user_id: str, limit: int = 50) -> List[Dict]:
        records = await GachaSimRecord.get_history(user_id, limit)
        return [
            {
                "name": r.name,
                "star": r.star,
                "type": r.item_type,
                "is_up": r.is_up,
                "pity_count": r.pity_count,
                "pool_type": r.pool_type,
                "created_at": r.created_at,
            }
            for r in (records or [])
        ]

    # ─── 特征码操作 ───

    async def get_signature(self, user_id: str) -> Optional[str]:
        """获取用户特征码"""
        return await GachaSimSignature.get_signature(user_id)

    async def set_signature(self, user_id: str, code: str) -> None:
        """设置用户特征码"""
        await GachaSimSignature.set_signature(user_id, code)

    async def check_code_exists(self, code: str) -> bool:
        """检查特征码是否已存在"""
        return await GachaSimSignature.check_code_exists(code)

    async def generate_signature(self, user_id: str) -> str:
        """生成随机9位数字特征码（从100000000开始），确保不重复，自动绑定并返回"""
        max_attempts = 100
        for _ in range(max_attempts):
            # 生成9位数字特征码，范围 100000000 ~ 999999999
            code = str(random.randint(100000000, 999999999))
            # 检查是否已存在
            if not await self.check_code_exists(code):
                # 绑定到用户
                await self.set_signature(user_id, code)
                logger.info(f"[模拟抽卡] 用户 {user_id} 生成特征码: {code}")
                return code
        # 如果尝试100次都无法生成唯一码，抛出异常
        raise ValueError("无法生成唯一的特征码")


data_manager = DataManager()
