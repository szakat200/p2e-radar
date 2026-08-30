"""Каталог игр solgames: /games (списки) и /game <slug> (карточка)."""
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatters import format_game, format_game_row
from db.models import Game

router = Router()

LIST_LIMIT = 10
NEW_DAYS = 30

MODES = {
    "new": "🆕 Свежие запуски (30 дней)",
    "top": "🏆 Топ по капитализации",
    "online": "👥 С живым онлайном",
    "safe": "🛡 Наименее рискованные",
    "notoken": "🌱 Без токена — ранний вход",
}
HELP = ("Режимы: /games new · top · online · safe · notoken\n"
        "Карточка игры: /game &lt;название&gt;")


def _base_query():
    return select(Game).where(Game.inactive.is_(False))


@router.message(Command("games"))
async def cmd_games(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    mode = args[1].strip().lower() if len(args) > 1 else "new"
    if mode not in MODES:
        await message.answer(f"Неизвестный режим «{mode}».\n\n{HELP}")
        return

    query = _base_query()
    if mode == "new":
        since = (date.today() - timedelta(days=NEW_DAYS)).isoformat()
        query = query.where(Game.launch_date >= since).order_by(Game.launch_date.desc())
    elif mode == "top":
        query = query.order_by(Game.market_cap.desc().nullslast())
    elif mode == "online":
        query = query.where(Game.live_online.isnot(None)) \
            .order_by(Game.live_online.desc())
    elif mode == "safe":
        query = query.where(Game.risk_score.isnot(None)) \
            .order_by(Game.risk_score.asc())
    else:  # notoken
        query = query.where(Game.token_mint.is_(None)) \
            .order_by(Game.launch_date.desc().nullslast())

    games = list((await db.execute(query.limit(LIST_LIMIT))).scalars().all())
    if not games:
        await message.answer(
            "Пусто — синк каталога игр ещё не отработал (раз в час).\n\n" + HELP)
        return
    rows = [format_game_row(i + 1, g) for i, g in enumerate(games)]
    await message.answer(
        f"<b>{MODES[mode]}</b>\n\n" + "\n\n".join(rows) + f"\n\n{HELP}",
        disable_web_page_preview=True)


@router.message(Command("game"))
async def cmd_game(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажи игру: /game kintara")
        return
    needle = args[1].strip().lower()

    game = (await db.execute(
        _base_query().where(Game.slug == needle))).scalar_one_or_none()
    if game is None:
        game = (await db.execute(
            _base_query().where(Game.name.ilike(f"%{needle}%"))
            .order_by(Game.market_cap.desc().nullslast()))).scalars().first()
    if game is None:
        await message.answer("Не нашёл такую игру. Список: /games new")
        return

    text = format_game(game)
    if game.token_mint:
        text += f"\n\nПолная проверка токена: /check {game.token_mint}"
    await message.answer(text, disable_web_page_preview=True)
