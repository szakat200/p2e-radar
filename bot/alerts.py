"""Проактивные алерты админу. Дедуп через alert_log (unique constraint)."""
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatters import esc, fmt_usd
from config import config
from db.models import AlertLog, Token, TokenSnapshot

logger = logging.getLogger(__name__)


async def _send_once(db: AsyncSession, bot: Bot, alert_type: str,
                     entity_key: str, fingerprint: str, text: str) -> bool:
    """Отправить алерт, если такой ещё не отправлялся. True = отправлен."""
    if not config.ADMIN_ID:
        return False
    db.add(AlertLog(alert_type=alert_type, entity_key=entity_key,
                    fingerprint=fingerprint, message=text))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False  # уже отправляли
    try:
        await bot.send_message(config.ADMIN_ID, text)
    except Exception:
        logger.exception("alert send failed: %s %s", alert_type, entity_key)
    return True


async def send_new_catalog_alerts(db: AsyncSession, bot: Bot,
                                  new_tokens: list[Token]) -> None:
    """Новый P2E-токен появился в каталоге CoinGecko×Solana."""
    # Поля -> кортежи до отправки: rollback при дедупе инвалидирует ORM-объекты
    rows = [
        (t.mint, t.coingecko_id, t.symbol, t.name,
         list(t.categories or []), t.market_cap)
        for t in new_tokens
    ]
    for mint, cg_id, symbol, name, categories, market_cap in rows:
        text = (
            f"🆕 <b>Новая игра в каталоге</b>\n\n"
            f"<b>{esc(symbol or '?')}</b> {esc(name or '')}\n"
            f"Категории: {esc(', '.join(categories))}\n"
            f"Market cap: {fmt_usd(market_cap)}\n"
            f"<code>{esc(mint)}</code>\n\n"
            f"Проверить: /check {esc(mint)}"
        )
        await _send_once(db, bot, "NEW_CATALOG_TOKEN", mint, cg_id or mint, text)


async def send_token_alerts(db: AsyncSession, bot: Bot, token: Token,
                            prev_flag_codes: set[str]) -> None:
    """Дельта-алерты по watched-токену: ликвидность, цена, новые флаги."""
    if not token.watched:
        return
    # Все поля токена — в локальные переменные ДО первого _send_once:
    # rollback при дедупе инвалидирует ORM-объект, и ленивая загрузка упадёт
    token_id = token.id
    mint = token.mint
    liquidity_usd = token.liquidity_usd
    price_usd = token.price_usd
    risk_score = token.risk_score
    risk_flags = list(token.risk_flags or [])
    label = f"<b>{esc(token.symbol or mint[:8])}</b>"
    today = date.today().isoformat()

    # Падение ликвидности против максимума за 24ч
    day_ago = datetime.utcnow() - timedelta(hours=24)
    snaps = (await db.execute(
        select(TokenSnapshot.liquidity_usd, TokenSnapshot.price_usd)
        .where(TokenSnapshot.token_id == token_id, TokenSnapshot.ts >= day_ago)
    )).all()
    liqs = [s.liquidity_usd for s in snaps if s.liquidity_usd]
    prices = [s.price_usd for s in snaps if s.price_usd]

    if liquidity_usd and liqs:
        max_liq = max(liqs)
        if max_liq > 0 and liquidity_usd < max_liq * (1 - config.ALERT_LIQ_DROP_PCT):
            drop = (1 - liquidity_usd / max_liq) * 100
            await _send_once(
                db, bot, "LIQUIDITY_DROP", mint, f"liqdrop:{today}",
                f"💧 <b>Падение ликвидности</b> {label}\n"
                f"−{drop:.0f}% за 24ч: {fmt_usd(max_liq)} → {fmt_usd(liquidity_usd)}\n"
                f"<code>{esc(mint)}</code>")

    if price_usd and prices:
        ref_price = prices[0]  # самый старый снапшот в окне
        if ref_price > 0 and price_usd < ref_price * (1 - config.ALERT_PRICE_DROP_PCT):
            drop = (1 - price_usd / ref_price) * 100
            await _send_once(
                db, bot, "PRICE_DROP", mint, f"pricedrop:{today}",
                f"📉 <b>Обвал цены</b> {label}\n"
                f"−{drop:.0f}% за 24ч: {fmt_usd(ref_price)} → {fmt_usd(price_usd)}\n"
                f"<code>{esc(mint)}</code>")
        elif ref_price > 0 and price_usd > ref_price * (1 + config.ALERT_PRICE_PUMP_PCT):
            # Урок 3-летнего анализа: памп в медвежьем секторе — точка выхода,
            # а не подтверждение роста (AXS янв 2026: +270% -> -70%)
            pump = (price_usd / ref_price - 1) * 100
            await _send_once(
                db, bot, "PRICE_PUMP", mint, f"pricepump:{today}",
                f"🚀 <b>Памп</b> {label}: +{pump:.0f}% за 24ч "
                f"({fmt_usd(ref_price)} → {fmt_usd(price_usd)})\n"
                f"💡 Исторически памп P2E-токена — окно фиксации прибыли, "
                f"а не сигнал на вход.\n"
                f"<code>{esc(mint)}</code>")

    # Новые critical/high флаги
    current = {f["code"]: f for f in risk_flags}
    for code, flag in current.items():
        if code in prev_flag_codes or flag["severity"] not in ("critical", "high"):
            continue
        await _send_once(
            db, bot, "NEW_RED_FLAG", mint, code,
            f"🚩 <b>Новый красный флаг</b> {label}\n"
            f"{esc(flag['title'])} — {esc(flag['detail'])}\n"
            f"Риск теперь: {risk_score}/100\n"
            f"<code>{esc(mint)}</code>")
