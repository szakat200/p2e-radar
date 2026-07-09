"""CoinGecko: каталог P2E/gaming токенов на Solana с mint-адресами.

Два запроса: /coins/list?include_platform=true (тяжёлый, кэш 24ч в модуле)
+ /coins/markets?category=... Пересечение даёт Solana-токены категории с mint.
Проверено 09.07.2026: категория play-to-earn ∩ solana = ~42 токена.
"""
import asyncio
import logging
import time
from datetime import datetime

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import Token

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 3.0  # keyless CoinGecko: ~10-15 req/min, не наглеем
_TIMEOUT = aiohttp.ClientTimeout(total=60)  # coins/list весит несколько МБ

CATEGORIES = ["play-to-earn", "gaming"]

# Кэш mint-маппинга: {coingecko_id: solana_mint}
_PLATFORMS_CACHE: dict[str, str] = {}
_PLATFORMS_CACHE_TS: float = 0.0
_PLATFORMS_TTL = 24 * 3600


async def _get(http: aiohttp.ClientSession, path: str, params: dict | None = None) -> list | dict | None:
    url = f"{config.COINGECKO_BASE}{path}"
    try:
        async with http.get(url, params=params, timeout=_TIMEOUT) as resp:
            if resp.status == 429:
                logger.warning("CoinGecko 429, backoff 30s")
                await asyncio.sleep(30)
                return None
            if resp.status != 200:
                logger.warning("CoinGecko %s -> HTTP %s", path, resp.status)
                return None
            return await resp.json()
    except Exception as e:
        logger.error("CoinGecko error %s: %s", path, e)
        return None


async def _solana_mints(http: aiohttp.ClientSession) -> dict[str, str]:
    """coingecko_id -> solana mint, кэш 24ч."""
    global _PLATFORMS_CACHE, _PLATFORMS_CACHE_TS
    if _PLATFORMS_CACHE and time.time() - _PLATFORMS_CACHE_TS < _PLATFORMS_TTL:
        return _PLATFORMS_CACHE
    data = await _get(http, "/api/v3/coins/list", {"include_platform": "true"})
    if not isinstance(data, list):
        return _PLATFORMS_CACHE  # старый кэш лучше, чем ничего
    mapping = {}
    for c in data:
        mint = (c.get("platforms") or {}).get("solana")
        if mint:
            mapping[c["id"]] = mint
    _PLATFORMS_CACHE = mapping
    _PLATFORMS_CACHE_TS = time.time()
    logger.info("CoinGecko platforms cache: %d solana coins", len(mapping))
    return mapping


async def run_catalog_sync(db: AsyncSession) -> list[Token]:
    """Синк каталога. Возвращает список НОВЫХ токенов (для алертов).

    Если таблица была пуста (первый сид) — вернёт [], чтобы не заспамить алертами.
    """
    existing_result = await db.execute(select(Token.mint))
    existing_mints = {m for (m,) in existing_result.all()}
    is_first_seed = not existing_mints

    new_tokens: list[Token] = []
    async with aiohttp.ClientSession() as http:
        mints = await _solana_mints(http)
        if not mints:
            logger.warning("CoinGecko catalog sync skipped: no platform mapping")
            return []

        seen_ids: set[str] = set()
        for category in CATEGORIES:
            await asyncio.sleep(_REQUEST_DELAY)
            coins = await _get(http, "/api/v3/coins/markets", {
                "vs_currency": "usd", "category": category,
                "order": "market_cap_desc", "per_page": "250", "page": "1",
            })
            if not isinstance(coins, list):
                continue
            for coin in coins:
                cid = coin["id"]
                mint = mints.get(cid)
                if not mint or cid in seen_ids:
                    continue
                seen_ids.add(cid)

                if mint in existing_mints:
                    # обновляем категории/имя у существующего
                    result = await db.execute(select(Token).where(Token.mint == mint))
                    token = result.scalar_one_or_none()
                    if token and token.categories and category not in token.categories:
                        token.categories = [*token.categories, category]
                    continue

                token = Token(
                    mint=mint,
                    symbol=(coin.get("symbol") or "").upper() or None,
                    name=coin.get("name"),
                    source="catalog",
                    coingecko_id=cid,
                    categories=[category],
                    market_cap=coin.get("market_cap"),
                    price_usd=coin.get("current_price"),
                    volume_h24=coin.get("total_volume"),
                    price_change_h24=coin.get("price_change_percentage_24h"),
                    metrics_updated_at=datetime.utcnow(),
                )
                db.add(token)
                existing_mints.add(mint)
                new_tokens.append(token)

    await db.commit()
    logger.info("Catalog sync: %d new tokens (first_seed=%s)", len(new_tokens), is_first_seed)
    return [] if is_first_seed else new_tokens
