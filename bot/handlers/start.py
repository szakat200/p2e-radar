from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router()

HELP = (
    "<b>☢️ Solana P2E Radar</b>\n\n"
    "Сканер P2E-токенов на Solana: рынок, on-chain безопасность, red flags.\n\n"
    "<b>Команды:</b>\n"
    "/check <code>&lt;mint&gt;</code> — разбор рисков токена\n"
    "/watch <code>&lt;mint&gt;</code> — добавить в вотчлист (мониторинг + алерты)\n"
    "/unwatch <code>&lt;mint&gt;</code> — убрать из вотчлиста\n"
    "/watchlist — мой вотчлист\n"
    "/games — топ P2E-игр на Solana (каталог CoinGecko)\n"
    "/games new — новые в каталоге за 7 дней\n\n"
    "Алерты приходят автоматически: падение ликвидности &gt;30%, "
    "цены &gt;40%, новые критические флаги, новые игры в каталоге."
)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)
