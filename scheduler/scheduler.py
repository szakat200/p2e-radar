"""APScheduler: периодические синки + алерты."""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


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
