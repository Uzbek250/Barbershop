"""Ma'lumotlar bazasi: jadvallar va ulanish."""
import ssl
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, String, UniqueConstraint
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import config

WAITING, SERVING, DONE, CANCELLED, SKIPPED = "waiting", "serving", "done", "cancelled", "skipped"
ACTIVE = (WAITING, SERVING)


def now() -> datetime:
    return datetime.now(config.TZ).replace(tzinfo=None)


def today() -> date:
    return datetime.now(config.TZ).date()


class Base(DeclarativeBase):
    pass


class QueueEntry(Base):
    """Bitta kunlik navbatdagi bitta mijoz."""

    __tablename__ = "queue_entries"
    __table_args__ = (UniqueConstraint("queue_date", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_date: Mapped[date] = mapped_column(Date, index=True)
    number: Mapped[int]  # shu kundagi tartib raqami (har kuni 1 dan)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)  # None = admin qo'lda qo'shgan
    name: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default=WAITING, index=True)
    ticket_message_id: Mapped[int | None] = mapped_column(BigInteger)  # jonli yangilanadigan xabar
    notified_called: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_near: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    called_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


def _make_engine():
    url = make_url(config.DATABASE_URL)
    connect_args = {}
    if url.drivername.startswith("postgres"):  # Render/Neon: postgres:// -> asyncpg
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        url = url.set(drivername="postgresql+asyncpg", query=query)
        if sslmode and sslmode != "disable":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ctx
    return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
