"""Модели БД: игры, токены, снапшоты метрик, on-chain безопасность, лог алертов."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Game(Base):
    """Игра на Solana из каталога solgames.buzz — основная сущность радара.

    Игра может быть без токена (token_mint = None): такие тоже интересны,
    ранний вход в них обычно и есть весь смысл.
    """

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    solgames_id: Mapped[int | None] = mapped_column(Integer)

    name: Mapped[str | None] = mapped_column(String(160))
    tagline: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(String(64), index=True)
    tags: Mapped[list | None] = mapped_column(JSON)

    url: Mapped[str | None] = mapped_column(String(256))
    twitter: Mapped[str | None] = mapped_column(String(256))
    solgames_url: Mapped[str | None] = mapped_column(String(256))
    image_url: Mapped[str | None] = mapped_column(String(512))

    launch_date: Mapped[str | None] = mapped_column(String(16), index=True)  # YYYY-MM-DD
    launch_stage: Mapped[str | None] = mapped_column(String(32))   # mainnet | beta | alpha…
    launch_access: Mapped[str | None] = mapped_column(String(32))  # open | invite | waitlist
    status: Mapped[str | None] = mapped_column(String(32))         # enriched | new | verified

    # Внимание рынка
    buzz_score: Mapped[float | None] = mapped_column(Float)
    buzz_delta_24h: Mapped[float | None] = mapped_column(Float)
    live_online: Mapped[int | None] = mapped_column(Integer)  # игроков онлайн, если игра отдаёт
    mention_count: Mapped[int | None] = mapped_column(Integer)
    twitter_followers: Mapped[int | None] = mapped_column(Integer)

    # Токен игры (может отсутствовать)
    token_mint: Mapped[str | None] = mapped_column(String(64), index=True)
    token_symbol: Mapped[str | None] = mapped_column(String(32))
    token_tradeable: Mapped[bool] = mapped_column(Boolean, default=False)
    price_usd: Mapped[float | None] = mapped_column(Float)
    price_change_h24: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    volume_h24: Mapped[float | None] = mapped_column(Float)
    ath_market_cap: Mapped[float | None] = mapped_column(Float)
    mcap_delta_24h: Mapped[float | None] = mapped_column(Float)
    pair_created_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Оценка риска токена игры — тот же risk_engine, что и для токенов
    risk_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(8))
    risk_flags: Mapped[list | None] = mapped_column(JSON)
    risk_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    inactive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class Token(Base):
    """Токен: из каталога CoinGecko (source=catalog) или добавлен вручную (source=manual)."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))

    source: Mapped[str] = mapped_column(String(16), default="manual")  # catalog | manual
    coingecko_id: Mapped[str | None] = mapped_column(String(128), index=True)
    image_url: Mapped[str | None] = mapped_column(String(256))
    categories: Mapped[list | None] = mapped_column(JSON)  # ["play-to-earn", "gaming"]
    description: Mapped[str | None] = mapped_column(Text)
    links: Mapped[dict | None] = mapped_column(JSON)  # {homepage, twitter, telegram, discord}

    watched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger)

    # Денормализованные последние метрики (для быстрого дашборда)
    price_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    volume_h24: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    price_change_h24: Mapped[float | None] = mapped_column(Float)
    ath_change_pct: Mapped[float | None] = mapped_column(Float)  # % от ATH (CoinGecko)
    pair_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    dex_id: Mapped[str | None] = mapped_column(String(32))
    pair_address: Mapped[str | None] = mapped_column(String(64))
    metrics_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Последняя оценка риска
    risk_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(8))  # low | medium | high
    risk_flags: Mapped[list | None] = mapped_column(JSON)  # [{code, severity, title, detail}]
    risk_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)  # последнее появление в каталоге


class TokenSnapshot(Base):
    """История метрик — для дельта-алертов (падение ликвидности/цены)."""

    __tablename__ = "token_snapshots"
    __table_args__ = (Index("ix_snapshot_token_ts", "token_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    price_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    volume_h24: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)


class TokenSecurity(Base):
    """On-chain данные безопасности. Все поля nullable = «неизвестно»."""

    __tablename__ = "token_security"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), unique=True)
    mint_authority_active: Mapped[bool | None] = mapped_column(Boolean)
    freeze_authority_active: Mapped[bool | None] = mapped_column(Boolean)
    top10_holder_pct: Mapped[float | None] = mapped_column(Float)
    lp_locked_pct: Mapped[float | None] = mapped_column(Float)
    rugcheck_score: Mapped[int | None] = mapped_column(Integer)
    holders_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(16))  # rugcheck | rpc
    raw: Mapped[dict | None] = mapped_column(JSON)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertLog(Base):
    """Дедуп отправленных алертов: unique(alert_type, entity_key, fingerprint)."""

    __tablename__ = "alert_log"
    __table_args__ = (
        UniqueConstraint("alert_type", "entity_key", "fingerprint", name="uq_alert_dedup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(32))
    entity_key: Mapped[str] = mapped_column(String(64))  # mint или coingecko_id
    fingerprint: Mapped[str] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
