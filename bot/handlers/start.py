from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router()

HELP = (
    "<b>☢️ Solana P2E Radar</b>\n\n"
    "Радар игр на Solana: каталог solgames.buzz + проверка токена "
    "(рынок, on-chain, red flags).\n\n"
    "<b>Игры:</b>\n"
    "/games — свежие запуски за 30 дней\n"
    "/games top — топ по капитализации\n"
    "/games online — с живым онлайном\n"
    "/games safe — наименее рискованные\n"
    "/games notoken — без токена (ранний вход)\n"
    "/game <code>&lt;название&gt;</code> — карточка игры\n\n"
    "<b>Токены:</b>\n"
    "/check <code>&lt;mint&gt;</code> — разбор рисков токена\n"
    "/watch <code>&lt;mint&gt;</code> — в вотчлист (мониторинг + алерты)\n"
    "/unwatch <code>&lt;mint&gt;</code> — убрать из вотчлиста\n"
    "/watchlist — мой вотчлист\n\n"
    "Алерты приходят автоматически: новая игра в каталоге, падение "
    "ликвидности &gt;30%, цены &gt;40%, новые критические флаги."
)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)
