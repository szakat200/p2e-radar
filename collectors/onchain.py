"""On-chain безопасность: RugCheck (основной) -> Solana RPC (фоллбек) -> None.

Формат ответа RugCheck /v1/tokens/{mint}/report проверен 09.07.2026:
  token.mintAuthority / token.freezeAuthority (null = отозваны),
  topHolders[].pct, score_normalised в /report/summary.
"""
import asyncio
import logging
from datetime import datetime

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import Token, TokenSecurity

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 1.0
_TIMEOUT = aiohttp.ClientTimeout(total=15)
STALE_HOURS = 6


async def _rugcheck(http: aiohttp.ClientSession, mint: str) -> dict | None:
    url = f"{config.RUGCHECK_BASE}/v1/tokens/{mint}/report"
    try:
        async with http.get(url, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning("RugCheck %s -> HTTP %s", mint[:8], resp.status)
                return None
            data = await resp.json()
    except Exception as e:
        logger.error("RugCheck error %s: %s", mint[:8], e)
        return None

    token_info = data.get("token") or {}
    top_holders = data.get("topHolders") or []
    # LP-пул обычно крупнейший холдер; считаем топ-10 по всем аккаунтам как есть —
    # это верхняя оценка концентрации (консервативно в сторону риска)
    top10_pct = sum(h.get("pct") or 0 for h in top_holders[:10]) or None

    markets = data.get("markets") or []
    lp_locked = None
    for m in markets:
        lp = (m.get("lp") or {}).get("lpLockedPct")
        if lp is not None:
            lp_locked = max(lp_locked or 0, lp)

    return {
        "mint_authority_active": token_info.get("mintAuthority") is not None,
        "freeze_authority_active": token_info.get("freezeAuthority") is not None,
        "top10_holder_pct": top10_pct,
        "lp_locked_pct": lp_locked,
        "rugcheck_score": data.get("score_normalised") or data.get("score"),
        "holders_count": data.get("totalHolders"),
        "source": "rugcheck",
    }


async def _rpc(http: aiohttp.ClientSession, method: str, params: list) -> dict | None:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with http.post(config.SOLANA_RPC_URL, json=body, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning("RPC %s -> HTTP %s", method, resp.status)
                return None
            data = await resp.json()
            return data.get("result")
    except Exception as e:
        logger.error("RPC %s error: %s", method, e)
        return None


async def _solana_rpc(http: aiohttp.ClientSession, mint: str) -> dict | None:
    """Фоллбек без ключа: authority из getAccountInfo, концентрация из largest accounts."""
    acc = await _rpc(http, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    if not acc or not acc.get("value"):
        return None
    info = ((acc["value"].get("data") or {}).get("parsed") or {}).get("info") or {}

    top10_pct = None
    supply_res = await _rpc(http, "getTokenSupply", [mint])
    largest = await _rpc(http, "getTokenLargestAccounts", [mint])
    if supply_res and largest:
        try:
            supply = float(supply_res["value"]["amount"])
            top10 = sum(float(a["amount"]) for a in largest["value"][:10])
            if supply > 0:
                top10_pct = top10 / supply * 100
        except (KeyError, ValueError, TypeError):
            pass

    return {
        "mint_authority_active": info.get("mintAuthority") is not None,
        "freeze_authority_active": info.get("freezeAuthority") is not None,
        "top10_holder_pct": top10_pct,
        "lp_locked_pct": None,  # RPC не знает про LP-локи
        "rugcheck_score": None,
        "holders_count": None,
        "source": "rpc",
    }


async def get_security(http: aiohttp.ClientSession, mint: str) -> dict | None:
    """Цепочка: RugCheck -> RPC -> None. None = «неизвестно», не ошибка."""
    sec = await _rugcheck(http, mint)
    if sec is None:
        sec = await _solana_rpc(http, mint)
    return sec


async def upsert_security(db: AsyncSession, token: Token, sec: dict | None) -> None:
    if sec is None:
        return  # сохраняем старые данные, checked_at не трогаем
    result = await db.execute(
        select(TokenSecurity).where(TokenSecurity.token_id == token.id))
    row = result.scalar_one_or_none()
    if row is None:
        row = TokenSecurity(token_id=token.id)
        db.add(row)
    row.mint_authority_active = sec["mint_authority_active"]
    row.freeze_authority_active = sec["freeze_authority_active"]
    row.top10_holder_pct = sec["top10_holder_pct"]
    row.lp_locked_pct = sec["lp_locked_pct"]
    row.rugcheck_score = sec["rugcheck_score"]
    row.holders_count = sec["holders_count"]
    row.source = sec["source"]
    row.checked_at = datetime.utcnow()


async def run_onchain_sync(db: AsyncSession) -> list[Token]:
    """Обновить security для watched-токенов со stale-данными (>6ч)."""
    result = await db.execute(select(Token).where(Token.watched.is_(True)))
    tokens = list(result.scalars().all())
    if not tokens:
        return []

    sec_rows = await db.execute(select(TokenSecurity))
    by_token = {s.token_id: s for s in sec_rows.scalars().all()}
    now = datetime.utcnow()

    updated: list[Token] = []
    async with aiohttp.ClientSession() as http:
        for token in tokens:
            existing = by_token.get(token.id)
            if existing and existing.checked_at and \
                    (now - existing.checked_at).total_seconds() < STALE_HOURS * 3600:
                continue
            sec = await get_security(http, token.mint)
            await upsert_security(db, token, sec)
            updated.append(token)
            await asyncio.sleep(_REQUEST_DELAY)

    await db.commit()
    logger.info("Onchain sync: %d tokens refreshed", len(updated))
    return updated
