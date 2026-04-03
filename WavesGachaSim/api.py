"""鸣潮抽卡模拟器 - API 配置与请求"""
from typing import Any, Dict, List, Optional

import httpx
from gsuid_core.logger import logger

# =============================================
# API 配置
# =============================================

# 卡池数据 API
POOL_API_BASE = "https://wh.loping151.site"
POOL_API_URL = f"{POOL_API_BASE}/api/waves/pool/list"

# 请求超时（秒）
REQUEST_TIMEOUT = 15

# 全局单例 Client（连接池复用）
_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """获取或创建全局单例 HTTP 客户端"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    return _http_client


async def close_client() -> None:
    """关闭全局 HTTP 客户端（插件卸载时调用）"""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# =============================================
# API 请求
# =============================================

async def fetch_pool_list() -> Optional[List[Dict[str, Any]]]:
    """
    从 API 获取卡池列表

    Returns:
        成功返回卡池列表 (list of dict)，失败返回 None
    """
    try:
        client = _get_client()
        resp = await client.get(POOL_API_URL)

        if resp.status_code != 200:
            logger.warning(f"[模拟抽卡] API 返回 {resp.status_code}")
            return None

        try:
            raw_data = resp.json()
        except Exception as e:
            logger.warning(f"[模拟抽卡] API 响应不是有效 JSON: {e}")
            return None

        # 类型校验：确保返回的是列表
        if not isinstance(raw_data, list):
            if isinstance(raw_data, dict):
                pools = raw_data.get("data", [])
                if not isinstance(pools, list):
                    logger.warning(f"[模拟抽卡] API 返回的 data 不是列表: {type(pools)}")
                    return None
            else:
                logger.warning(f"[模拟抽卡] API 返回类型不是 list 或 dict: {type(raw_data)}")
                return None
        else:
            pools = raw_data

        logger.info(f"[模拟抽卡] API 获取到 {len(pools)} 个卡池")
        return pools

    except httpx.TimeoutException:
        logger.error("[模拟抽卡] API 请求超时")
        return None
    except Exception as e:
        logger.error(f"[模拟抽卡] API 请求异常: {e}")
        return None
