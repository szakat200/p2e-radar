import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatters import format_check_report, format_watchlist_row
from bot.services import is_valid_mint, watch_token
from db.models import Token

logger = logging.getLogger(__name__)
router = Router()


def _extract_mint(message: Message) -> str | None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return None
    mint = args[1].strip()
    return mint if is_valid_mint(mint) else None


@router.message(Command("watch"))
async def cmd_watch(message: Message, db: AsyncSession) -> None:
    mint = _extract_mint(message)
    if not mint:
        await message.answer("Использование: /watch <code>&lt;mint&gt;</code>")
        return
    waiting = await message.answer("🔍 Проверяю и добавляю в вотчлист…")
    try:
        token, market, security, report = await watch_token(db, mint, message.from_user.id)
        text = format_check_report(mint, market, security, report)
        await waiting.edit_text(text + "\n\n✅ <b>Добавлен в вотчлист</b> — буду следить.")
    except Exception:
        logger.exception("watch failed for %s", mint)
        await waiting.edit_text("⚠️ Не удалось добавить токен, попробуй позже.")


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, db: AsyncSession) -> None:
    mint = _extract_mint(message)
    if not mint:
        await message.answer("Использование: /unwatch <code>&lt;mint&gt;</code>")
        return
    token = (await db.execute(select(Token).where(Token.mint == mint))).scalar_one_or_none()
    if not token or not token.watched:
        await message.answer("Этого токена нет в вотчлисте.")
        return
    token.watched = False
    await db.commit()
    await message.answer(f"🗑 <b>{token.symbol or mint[:8]}</b> убран из вотчлиста.")


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, db: AsyncSession) -> None:
    result = await db.execute(
        select(Token).where(Token.watched.is_(True)).order_by(Token.risk_score.desc()))
    tokens = list(result.scalars().all())
    if not tokens:
        await message.answer("Вотчлист пуст. Добавь токен: /watch <code>&lt;mint&gt;</code>")
        return
    rows = [format_watchlist_row(t) for t in tokens]
    await message.answer("<b>👁 Вотчлист</b>\n\n" + "\n\n".join(rows))
