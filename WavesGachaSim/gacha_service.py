"""鸣潮抽卡模拟器 - 核心抽卡逻辑"""
import random
from typing import Any, Dict, List, Optional

from gsuid_core.logger import logger


# 每日每池类型抽卡限制
DAILY_LIMIT = 300


class GachaService:
    """鸣潮抽卡核心服务"""

    # 五星基础概率
    BASE_5STAR_RATE = 0.008  # 0.8%
    # 4星基础概率
    BASE_4STAR_RATE = 0.06   # 6%

    @staticmethod
    def calculate_5star_rate(pity_count: int) -> float:
        """
        计算五星概率（基于保底递增机制）
        pity_count: 当前已抽次数（不含本次），即距离上次5星后累计抽了多少
        返回的是"第 pity_count+1 抽"的5星概率
        """
        draw_num = pity_count + 1  # 本次是第几抽
        if draw_num <= 65:
            return 0.008
        elif draw_num <= 70:
            # 66-70: 基础 + (draw_num - 65) * 4%
            return 0.008 + (draw_num - 65) * 0.04
        elif draw_num <= 75:
            # 71-75: 在70抽的基础上继续 + 每抽8%
            rate_at_70 = 0.008 + 5 * 0.04  # = 0.208
            return rate_at_70 + (draw_num - 70) * 0.08
        elif draw_num <= 78:
            # 76-78: 在75抽的基础上继续 + 每抽10%
            rate_at_75 = 0.008 + 5 * 0.04 + 5 * 0.08  # = 0.608
            return rate_at_75 + (draw_num - 75) * 0.10
        else:
            # 79抽及以上: 100%
            return 1.0

    @staticmethod
    def normalize_pool_type(pool_type: str) -> str:
        """标准化卡池类型: limited_char_xxx → limited_char"""
        if pool_type.startswith("limited_char"):
            return "limited_char"
        elif pool_type.startswith("limited_weapon"):
            return "limited_weapon"
        elif pool_type.startswith("standard_char"):
            return "standard_char"
        elif pool_type.startswith("standard_weapon"):
            return "standard_weapon"
        return pool_type

    @staticmethod
    def get_pool_group(pool_id: str) -> str:
        """获取卡池分组（用于每日限制计数）"""
        return GachaService.normalize_pool_type(pool_id)

    def draw_5star(
        self,
        pool: Dict[str, Any],
        guaranteed: bool = False,
    ) -> Dict[str, Any]:
        """
        抽取5星
        - 限定角色池: guaranteed → 必出UP；否则50/50
        - 限定武器池: 必出UP
        - 常驻池: 随机从 standard5star 中选
        """
        pool_type = pool.get("type", "")
        up_items = pool.get("up", {}).get("5star", [])
        standard_5star = pool.get("standard5star", [])

        if pool_type == "limited_char":
            if guaranteed and up_items:
                item = random.choice(up_items)
                return {"star": 5, "name": item["name"], "is_up": True,
                        "type": item.get("type", "character"),
                        "resource_id": item.get("resource_id", "")}
            # 50/50
            if up_items and random.random() < 0.5:
                item = random.choice(up_items)
                return {"star": 5, "name": item["name"], "is_up": True,
                        "type": item.get("type", "character"),
                        "resource_id": item.get("resource_id", "")}
            # 歪了
            if standard_5star:
                item = random.choice(standard_5star)
                return {"star": 5, "name": item["name"], "is_up": False,
                        "type": item.get("type", "character"),
                        "resource_id": item.get("resource_id", "")}

        elif pool_type == "limited_weapon":
            # 武器池必出UP
            if up_items:
                item = random.choice(up_items)
                return {"star": 5, "name": item["name"], "is_up": True,
                        "type": item.get("type", "weapon"),
                        "resource_id": item.get("resource_id", "")}

        # 常驻池 / fallback
        if standard_5star:
            item = random.choice(standard_5star)
            return {"star": 5, "name": item["name"], "is_up": False,
                    "type": item.get("type", "character"),
                    "resource_id": item.get("resource_id", "")}

        return {"star": 5, "name": "未知", "is_up": False, "type": "character", "resource_id": ""}

    def draw_4star(
        self,
        pool: Dict[str, Any],
        guaranteed: bool = False,
    ) -> Dict[str, Any]:
        """
        抽取4星
        - 限定池: guaranteed 或 50% 出 UP四星，否则出 standard4star
        - 常驻池: 随机从 standard4star
        """
        pool_type = pool.get("type", "")
        up_items = pool.get("up", {}).get("4star", [])
        standard_4star = pool.get("standard4star", [])

        if pool_type in ("limited_char", "limited_weapon"):
            if up_items and (guaranteed or random.random() < 0.5):
                item = random.choice(up_items)
                return {"star": 4, "name": item["name"], "is_up": True,
                        "type": item.get("type", "character"),
                        "resource_id": item.get("resource_id", "")}
            if standard_4star:
                item = random.choice(standard_4star)
                return {"star": 4, "name": item["name"], "is_up": False,
                        "type": item.get("type", "character"),
                        "resource_id": item.get("resource_id", "")}

        # 常驻池
        if standard_4star:
            item = random.choice(standard_4star)
            return {"star": 4, "name": item["name"], "is_up": False,
                    "type": item.get("type", "character"),
                    "resource_id": item.get("resource_id", "")}

        return {"star": 4, "name": "未知", "is_up": False, "type": "character", "resource_id": ""}

    def draw_3star(self, weapons_3star: List[str]) -> Dict[str, Any]:
        """抽取3星武器"""
        name = random.choice(weapons_3star) if weapons_3star else "未知3星武器"
        return {"star": 3, "name": name, "is_up": False, "type": "weapon", "resource_id": ""}

    def perform_draw(
        self,
        pool: Dict[str, Any],
        pity_data: Dict[str, Any],
        weapons_3star: List[str],
        count: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        执行抽卡

        Args:
            pool: 卡池配置（含 up, standard5star, standard4star, type）
            pity_data: 用户保底数据（会被就地修改）
            weapons_3star: 3星武器列表
            count: 抽卡次数

        Returns:
            抽卡结果列表
        """
        results: List[Dict[str, Any]] = []

        current_count = pity_data.get("current_count", 0)
        pity4 = pity_data.get("pity4", 0)
        guaranteed5 = pity_data.get("guaranteed5", False)
        guaranteed4 = pity_data.get("guaranteed4", False)

        for _ in range(count):
            current_count += 1
            pity4 += 1

            # 先判断5星
            rate_5 = self.calculate_5star_rate(current_count - 1)
            if rate_5 >= 1.0 or random.random() < rate_5:
                result = self.draw_5star(pool, guaranteed5)
                result["pity_count"] = current_count
                results.append(result)

                # 更新保底状态
                if result["is_up"]:
                    guaranteed5 = False
                else:
                    # 歪了，下次大保底
                    guaranteed5 = True

                current_count = 0
                pity4 = 0
                guaranteed4 = False

                # 记录5星
                pity_data["last_five_star"] = result["name"]
                continue

            # 判断4星 (10保底)
            if pity4 >= 10 or random.random() < self.BASE_4STAR_RATE:
                result = self.draw_4star(pool, guaranteed4)
                result["pity_count"] = pity4
                results.append(result)

                if result["is_up"]:
                    guaranteed4 = False
                else:
                    guaranteed4 = True

                pity4 = 0
                continue

            # 3星
            result = self.draw_3star(weapons_3star)
            result["pity_count"] = 0
            results.append(result)

        # 回写保底数据
        pity_data["current_count"] = current_count
        pity_data["pity4"] = pity4
        pity_data["guaranteed5"] = guaranteed5
        pity_data["guaranteed4"] = guaranteed4
        pity_data["total_count"] = pity_data.get("total_count", 0) + count

        return results


# 全局实例
gacha_service = GachaService()
