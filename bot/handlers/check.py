import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.formatters import format_check_report
from bot.services import is_valid_mint, live_check

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("check"))
async def cmd_check(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not is_valid_mint(args[1].strip()):
        await message.answer(
            "Пришли mint-адрес токена: /check <code>&lt;mint&gt;</code>\n"
            "Например: /check <code>2ABbnf3EzGfiMa3PE2bseAWwRD4jAE4KgE8YjSTxpump</code>")
        return
    mint = args[1].strip()

    waiting = await message.answer("🔍 Проверяю рынок и on-chain данные…")
    try:
        market, security, report = await live_check(mint)
        await waiting.edit_text(format_check_report(mint, market, security, report))
    except Exception:
        logger.exception("check failed for %s", mint)
        await waiting.edit_text("⚠️ Не удалось проверить токен, попробуй позже.")
