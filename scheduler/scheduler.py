"""APScheduler: периодические синки + алерты."""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


RISK_REFRESH_PER_RUN = 25  # сколько игр переоценивать за прогон (RugCheck ~1 req/сек)


async def _job_games(bot: Bot) -> None:
    """Основной синк: каталог игр solgames -> риск -> алерты о новых играх."""
    from sqlalchemy import select

    from bot.alerts import send_new_game_alerts
    from bot.services import score_games
    from collectors.solgames import run_games_sync
    from db.models import Game

    async with AsyncSessionLocal() as db:
        new_games = await run_games_sync(db)

        # Новые — в первую очередь, остальные добираем по давности оценки
        stale = (await db.execute(
            select(Game)
            .where(Game.inactive.is_(False), Game.token_tradeable.is_(True))
            .order_by(Game.risk_updated_at.asc().nullsfirst())
            .limit(RISK_REFRESH_PER_RUN))).scalars().all()
        queue = list(new_games) + [g for g in stale if g not in new_games]
        await score_games(db, queue[:RISK_REFRESH_PER_RUN])
        await db.commit()

        if new_games:
            await send_new_game_alerts(db, bot, new_games)


async def _job_catalog(bot: Bot) -> None:
    from bot.alerts import send_new_catalog_alerts
    from collectors.coingecko import run_catalog_sync
    async with AsyncSessionLocal() as db:
        new_tokens = await run_catalog_sync(db)
        if new_tokens:
            await send_new_catalog_alerts(db, bot, new_tokens)


async def _job_market(bot: Bot) -> None:
    from bot.alerts import send_token_alerts
    from bot.services import recompute_risk
    from collectors.dexscreener import run_dexscreener_sync
    async with AsyncSessionLocal() as db:
        tokens = await run_dexscreener_sync(db)
        for token in tokens:
            prev_codes = {f["code"] for f in (token.risk_flags or [])}
            await recompute_risk(db, token)
            await db.commit()
            await send_token_alerts(db, bot, token, prev_codes)


async def _job_onchain(bot: Bot) -> None:
    from bot.alerts import send_token_alerts
    from bot.services import recompute_risk
    from collectors.onchain import run_onchain_sync
    async with AsyncSessionLocal() as db:
        tokens = await run_onchain_sync(db)
        for token in tokens:
            prev_codes = {f["code"] for f in (token.risk_flags or [])}
            await recompute_risk(db, token)
            await db.commit()
            await send_token_alerts(db, bot, token, prev_codes)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _job_games, args=[bot],
        trigger=IntervalTrigger(minutes=config.GAMES_SYNC_MINUTES),
        id="games_sync", name="solgames games sync",
        replace_existing=True, misfire_grace_time=600)
    scheduler.add_job(
        _job_catalog, args=[bot],
        trigger=IntervalTrigger(hours=config.CATALOG_SYNC_HOURS),
        id="catalog_sync", name="CoinGecko catalog sync",
        replace_existing=True, misfire_grace_time=600)
    scheduler.add_job(
        _job_market, args=[bot],
        trigger=IntervalTrigger(minutes=config.MARKET_SYNC_MINUTES),
        id="market_sync", name="DexScreener market sync",
        replace_existing=True, misfire_grace_time=120)
    scheduler.add_job(
        _job_onchain, args=[bot],
        trigger=IntervalTrigger(hours=config.ONCHAIN_SYNC_HOURS),
        id="onchain_sync", name="Onchain security sync",
        replace_existing=True, misfire_grace_time=600)
    return scheduler
