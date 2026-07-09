"""Solana P2E Radar — точка входа: Telegram-бот + scheduler в одном loop.

Веб-панель запускается отдельным процессом: uvicorn web_app:app --port 8010
"""
import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.filters import AdminFilter
from bot.handlers import router
from config import config
from db.database import AsyncSessionLocal, close_db, init_db
from scheduler.scheduler import create_scheduler

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with AsyncSessionLocal() as session:
            data["db"] = session
            return await handler(event, data)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан — заполни .env (см. .env.example)")

    await init_db()

    # HTML вместо MarkdownV2: символы токенов ($RELIC и т.п.) не требуют экранирования
    bot = Bot(config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    router.message.filter(AdminFilter())
    dp.include_router(router)

    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started: %s", [j.id for j in scheduler.get_jobs()])

    # Первый синк каталога — сразу, не ждать 6 часов
    from scheduler.scheduler import _job_catalog
    asyncio.create_task(_job_catalog(bot))

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
