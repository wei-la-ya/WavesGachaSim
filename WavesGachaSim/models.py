"""鸣潮抽卡模拟器 - SQLite 数据库模型"""

import time
from datetime import date
from typing import Any, Dict, List, Optional

from sqlmodel import Field, select
from sqlalchemy import delete, update
from sqlalchemy.sql import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import func

from gsuid_core.utils.database.base_models import BaseIDModel, with_session
from gsuid_core.webconsole.mount_app import PageSchema, GsAdminModel, site


# ==================== GachaSimPity (保底数据表) ====================
class GachaSimPity(BaseIDModel, table=True):
    """保底数据表"""

    __tablename__ = "GachaSimPity"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(title="用户ID")
    bot_id: str = Field(default="", title="平台")
    pool_type: str = Field(title="卡池类型")
    current_count: int = Field(default=0, title="当前5星计数")
    pity4: int = Field(default=0, title="当前4星计数")
    guaranteed5: bool = Field(default=False, title="5星大保底")
    guaranteed4: bool = Field(default=False, title="4星大保底")
    total_count: int = Field(default=0, title="总抽数")

    @classmethod
    @with_session
    async def get_pity(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
    ) -> Optional["GachaSimPity"]:
        """获取保底数据，不存在则返回 None"""
        result = await session.execute(
            select(cls).where(
                and_(cls.user_id == user_id, cls.pool_type == pool_type)
            )
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def save_pity(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
        current_count: int,
        pity4: int,
        guaranteed5: bool,
        guaranteed4: bool,
        total_count: int,
    ) -> None:
        """保存保底数据"""
        stmt = (
            update(cls)
            .where(and_(cls.user_id == user_id, cls.pool_type == pool_type))
            .values(
                current_count=current_count,
                pity4=pity4,
                guaranteed5=guaranteed5,
                guaranteed4=guaranteed4,
                total_count=total_count,
            )
        )
        result = await session.execute(stmt)

        if result.rowcount == 0:
            session.add(cls(
                user_id=user_id,
                pool_type=pool_type,
                current_count=current_count,
                pity4=pity4,
                guaranteed5=guaranteed5,
                guaranteed4=guaranteed4,
                total_count=total_count,
            ))

    @classmethod
    @with_session
    async def reset_pity(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
    ) -> None:
        """重置保底"""
        stmt = delete(cls).where(
            and_(cls.user_id == user_id, cls.pool_type == pool_type)
        )
        await session.execute(stmt)


# ==================== GachaSimRecord (出货记录表) ====================
class GachaSimRecord(BaseIDModel, table=True):
    """5星出货记录表"""

    __tablename__ = "GachaSimRecord"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(title="用户ID")
    bot_id: str = Field(default="", title="平台")
    pool_type: str = Field(title="卡池类型")
    name: str = Field(title="名称")
    star: int = Field(default=5, title="星级")
    item_type: str = Field(default="character", title="类型")
    is_up: bool = Field(default=False, title="是否UP")
    pity_count: int = Field(default=0, title="抽数")
    created_at: int = Field(default=0, title="时间戳")

    @classmethod
    @with_session
    async def add_record(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        pool_type: str,
        name: str,
        star: int,
        item_type: str,
        is_up: bool,
        pity_count: int,
    ) -> None:
        """新增记录"""
        session.add(cls(
            user_id=user_id,
            bot_id=bot_id,
            pool_type=pool_type,
            name=name,
            star=star,
            item_type=item_type,
            is_up=is_up,
            pity_count=pity_count,
            created_at=int(time.time()),
        ))

    @classmethod
    @with_session
    async def get_history(
        cls,
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> List["GachaSimRecord"]:
        """获取最近记录"""
        stmt = (
            select(cls)
            .where(cls.user_id == user_id)
            .order_by(cls.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def get_stats(
        cls,
        session: AsyncSession,
        user_id: str,
    ) -> Dict[str, Any]:
        """获取统计信息"""
        stmt = (
            select(func.count(cls.id))
            .where(and_(cls.user_id == user_id, cls.star == 5))
        )
        result = await session.execute(stmt)
        total_5star = result.scalar() or 0

        stmt = (
            select(func.count(cls.id))
            .where(and_(cls.user_id == user_id, cls.star == 4))
        )
        result = await session.execute(stmt)
        total_4star = result.scalar() or 0

        stmt = (
            select(func.count(cls.id))
            .where(cls.user_id == user_id, cls.is_up == True)  # noqa: E712
        )
        result = await session.execute(stmt)
        total_up = result.scalar() or 0

        stmt = (
            select(func.avg(cls.pity_count))
            .where(and_(cls.user_id == user_id, cls.star == 5))
        )
        result = await session.execute(stmt)
        avg_pity = result.scalar() or 0

        return {
            "total_5star": total_5star,
            "total_4star": total_4star,
            "total_up": total_up,
            "avg_pity": round(avg_pity, 1) if avg_pity else 0,
        }


# ==================== GachaSimPool (卡池选择表) ====================
class GachaSimPool(BaseIDModel, table=True):
    """卡池选择表"""

    __tablename__ = "GachaSimPool"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(title="用户ID")
    bot_id: str = Field(default="", title="平台")
    pool_type: str = Field(title="卡池类型")
    selected_pool_id: str = Field(default="", title="选中的卡池ID")

    @classmethod
    @with_session
    async def get_selected(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
    ) -> Optional[str]:
        """获取用户选择的卡池ID"""
        stmt = select(cls).where(
            and_(cls.user_id == user_id, cls.pool_type == pool_type)
        )
        result = await session.execute(stmt)
        record = result.scalars().first()
        return record.selected_pool_id if record else None

    @classmethod
    @with_session
    async def set_selected(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
        pool_id: str,
    ) -> None:
        """设置用户选择的卡池"""
        stmt = (
            update(cls)
            .where(and_(cls.user_id == user_id, cls.pool_type == pool_type))
            .values(selected_pool_id=pool_id)
        )
        result = await session.execute(stmt)

        if result.rowcount == 0:
            session.add(cls(
                user_id=user_id,
                pool_type=pool_type,
                selected_pool_id=pool_id,
            ))


# ==================== GachaSimDaily (每日计数表) ====================
class GachaSimDaily(BaseIDModel, table=True):
    """每日计数表"""

    __tablename__ = "GachaSimDaily"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(title="用户ID")
    pool_type: str = Field(title="卡池类型")
    date: str = Field(title="日期")
    count: int = Field(default=0, title="抽卡次数")

    @classmethod
    def _today(cls) -> str:
        """获取今天的日期字符串"""
        return date.today().strftime("%Y-%m-%d")

    @classmethod
    @with_session
    async def get_daily_count(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
    ) -> int:
        """获取今日已抽次数"""
        today = cls._today()
        stmt = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.pool_type == pool_type,
                cls.date == today,
            )
        )
        result = await session.execute(stmt)
        record = result.scalars().first()
        return record.count if record else 0

    @classmethod
    @with_session
    async def add_daily_count(
        cls,
        session: AsyncSession,
        user_id: str,
        pool_type: str,
        count: int,
    ) -> None:
        """增加每日次数"""
        today = cls._today()

        stmt = (
            update(cls)
            .where(
                and_(
                    cls.user_id == user_id,
                    cls.pool_type == pool_type,
                    cls.date == today,
                )
            )
            .values(count=cls.count + count)
        )
        result = await session.execute(stmt)

        if result.rowcount == 0:
            session.add(cls(
                user_id=user_id,
                pool_type=pool_type,
                date=today,
                count=count,
            ))


# ==================== GachaSimSignature (特征码表) ====================
class GachaSimSignature(BaseIDModel, table=True):
    """用户特征码表"""

    __tablename__ = "GachaSimSignature"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(title="用户ID")
    bot_id: str = Field(default="", title="平台")
    signature_code: str = Field(title="9位数字特征码")

    @classmethod
    @with_session
    async def get_signature(
        cls,
        session: AsyncSession,
        user_id: str,
    ) -> Optional[str]:
        """获取用户特征码"""
        stmt = select(cls).where(cls.user_id == user_id)
        result = await session.execute(stmt)
        record = result.scalars().first()
        return record.signature_code if record else None

    @classmethod
    @with_session
    async def set_signature(
        cls,
        session: AsyncSession,
        user_id: str,
        code: str,
    ) -> None:
        """设置/更新用户特征码"""
        stmt = select(cls).where(cls.user_id == user_id)
        result = await session.execute(stmt)
        record = result.scalars().first()

        if record:
            stmt = (
                update(cls)
                .where(cls.user_id == user_id)
                .values(signature_code=code)
            )
            await session.execute(stmt)
        else:
            session.add(cls(
                user_id=user_id,
                signature_code=code,
            ))

    @classmethod
    @with_session
    async def check_code_exists(
        cls,
        session: AsyncSession,
        code: str,
    ) -> bool:
        """检查特征码是否已被使用"""
        stmt = select(cls).where(cls.signature_code == code)
        result = await session.execute(stmt)
        return result.scalars().first() is not None


# ==================== Web 管理后台注册 ====================
@site.register_admin
class GachaSimPityAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="模拟抽卡-保底数据",
        icon="fa fa-diamond",
    )
    model = GachaSimPity


@site.register_admin
class GachaSimRecordAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="模拟抽卡-出货记录",
        icon="fa fa-history",
    )
    model = GachaSimRecord


@site.register_admin
class GachaSimPoolAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="模拟抽卡-卡池选择",
        icon="fa fa-exchange",
    )
    model = GachaSimPool


@site.register_admin
class GachaSimDailyAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="模拟抽卡-每日统计",
        icon="fa fa-calendar",
    )
    model = GachaSimDaily


@site.register_admin
class GachaSimSignatureAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="模拟抽卡-特征码",
        icon="fa fa-qrcode",
    )
    model = GachaSimSignature
