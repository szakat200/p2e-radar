"""Общая логика проверки токена и игры — используется хендлерами и алертами."""
import asyncio
import logging
import re
from datetime import datetime

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analyzer.risk_engine import RiskReport, evaluate
from collectors.dexscreener import apply_market_to_token, get_market
from collectors.onchain import get_security, upsert_security
from collectors.solgames import to_market
from db.models import Game, Token, TokenSecurity, TokenSnapshot

logger = logging.getLogger(__name__)

_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")  # base58, без 0OIl


def is_valid_mint(text: str) -> bool:
    return bool(_MINT_RE.match(text))


async def live_check(mint: str) -> tuple[dict | None, dict | None, RiskReport]:
    """Живая проверка mint: рынок + on-chain + оценка риска."""
    async with aiohttp.ClientSession() as http:
        market = await get_market(http, mint)
        security = await get_security(http, mint)
    return market, security, evaluate(market, security, mint)


ONCHAIN_DELAY = 1.0  # пауза между RugCheck-запросами


async def score_games(db: AsyncSession, games: list[Game]) -> None:
    """Проставить играм риск их токена.

    Рынок берём из каталога solgames (он там уже свежий), из сети тянем
    только on-chain: mint/freeze authority, концентрация холдеров, LP.
    Игры без торгуемого токена получают risk_score = None — это не «чисто»,
    а «нечего оценивать», UI показывает их отдельно.
    """
    targets = [g for g in games if g.token_tradeable and g.token_mint]
    if not targets:
        return
    now = datetime.utcnow()
    async with aiohttp.ClientSession() as http:
        for game in targets:
            security = await get_security(http, game.token_mint)
            report = evaluate(to_market(game), security, game.token_mint)
            game.risk_score = report.score
            game.risk_level = report.level
            game.risk_flags = [f.as_dict() for f in report.flags]
            game.risk_updated_at = now
            await asyncio.sleep(ONCHAIN_DELAY)
    logger.info("Games risk: оценено %d игр", len(targets))


def apply_risk_to_token(token: Token, report: RiskReport) -> None:
    token.risk_score = report.score
    token.risk_level = report.level
    token.risk_flags = [f.as_dict() for f in report.flags]
    token.risk_updated_at = datetime.utcnow()


async def recompute_risk(db: AsyncSession, token: Token) -> RiskReport:
    """Пересчитать риск токена по данным из БД (без внешних запросов)."""
    market = None
    if token.metrics_updated_at and token.liquidity_usd is not None:
        market = {
            "price_usd": token.price_usd,
            "liquidity_usd": token.liquidity_usd,
            "volume_h24": token.volume_h24,
            "market_cap": token.market_cap,
            "price_change_h24": token.price_change_h24,
            "pair_created_at": token.pair_created_at,
            "ath_change_pct": token.ath_change_pct,
        }
    sec_row = (await db.execute(
        select(TokenSecurity).where(TokenSecurity.token_id == token.id)
    )).scalar_one_or_none()
    security = None
    if sec_row and sec_row.checked_at:
        security = {
            "mint_authority_active": sec_row.mint_authority_active,
            "freeze_authority_active": sec_row.freeze_authority_active,
            "top10_holder_pct": sec_row.top10_holder_pct,
            "lp_locked_pct": sec_row.lp_locked_pct,
            "holders_count": sec_row.holders_count,
        }
    report = evaluate(market, security, token.mint)
    apply_risk_to_token(token, report)
    return report


async def watch_token(db: AsyncSession, mint: str, user_id: int) \
        -> tuple[Token, dict | None, dict | None, RiskReport]:
    """Добавить в вотчлист (или включить watched) + сразу проверить и сохранить."""
    market, security, report = await live_check(mint)

    token = (await db.execute(select(Token).where(Token.mint == mint))).scalar_one_or_none()
    if token is None:
        token = Token(mint=mint, source="manual", added_by=user_id)
        db.add(token)
        await db.flush()  # получить token.id для snapshot/security
    token.watched = True

    apply_market_to_token(token, market)
    apply_risk_to_token(token, report)
    db.add(TokenSnapshot(
        token_id=token.id, price_usd=token.price_usd,
        liquidity_usd=token.liquidity_usd, volume_h24=token.volume_h24,
        market_cap=token.market_cap,
    ))
    await upsert_security(db, token, security)
    await db.commit()
    return token, market, security, report
