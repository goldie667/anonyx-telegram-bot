from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from bot.config import config

engine = create_async_engine(config.database_url, pool_pre_ping=True, pool_size=2, max_overflow=0, pool_recycle=1800)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interests: Mapped[str] = mapped_column(Text, default="")
    looking_gender: Mapped[str] = mapped_column(String(16), default="any")
    min_age: Mapped[int] = mapped_column(Integer, default=18)
    max_age: Mapped[int] = mapped_column(Integer, default=99)
    looking_country: Mapped[str] = mapped_column(String(64), default="any")
    match_interests: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int] = mapped_column(BigInteger)
    reported_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(128), default="User report")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Block(Base):
    __tablename__ = "blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blocker_id: Mapped[int] = mapped_column(BigInteger)
    blocked_id: Mapped[int] = mapped_column(BigInteger)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)

async def ensure_user(session: AsyncSession, tg_user) -> User:
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(id=tg_user.id, username=tg_user.username)
        session.add(user)
    else:
        user.username = tg_user.username
    await session.commit()
    return user

async def blocked_pair(session: AsyncSession, a: int, b: int) -> bool:
    q = select(Block.id).where(
        ((Block.blocker_id == a) & (Block.blocked_id == b)) |
        ((Block.blocker_id == b) & (Block.blocked_id == a))
    ).limit(1)
    return (await session.execute(q)).first() is not None
