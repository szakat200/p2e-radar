from aiogram import Router

from bot.handlers.check import router as check_router
from bot.handlers.games import router as games_router
from bot.handlers.start import router as start_router
from bot.handlers.watch import router as watch_router

router = Router()
router.include_router(start_router)
router.include_router(check_router)
router.include_router(watch_router)
router.include_router(games_router)
