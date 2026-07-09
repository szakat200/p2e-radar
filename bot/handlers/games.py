from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatters import format_catalog_row
from db.models import Token

router = Router()


@router.message(Command("games"))
async def cmd_games(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    mode = args[1].strip().lower() if len(args) > 1 else "top"

    query = select(Token).where(Token.source == "catalog")
    if mode == "new":
        week_ago = datetime.utcnow() - timedelta(days=7)
        query = query.where(Token.first_seen_at >= week_ago).order_by(
            Token.first_seen_at.desc())
        title = "🆕 Новые в каталоге за 7 дней"
    else:
        query = query.order_by(Token.market_cap.desc().nullslast())
        title = "🎮 Топ P2E-игр на Solana (по market cap)"

    tokens = list((await db.execute(query.limit(10))).scalars().all())
    if not tokens:
        await message.answer(
            "Каталог пуст" + (" — за 7 дней новых нет." if mode == "new"
                              else ". Синк каталога ещё не отработал."))
        return
    rows = [format_catalog_row(i + 1, t) for i, t in enumerate(tokens)]
    await message.answer(f"<b>{title}</b>\n\n" + "\n\n".join(rows)
                         + "\n\nПроверить: /check <code>&lt;mint&gt;</code>")
