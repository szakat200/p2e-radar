"""DexScreener: рыночные метрики токена по mint. Без API-ключа."""
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import Token, TokenSnapshot

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 0.35  # DexScreener: 300 req/min на endpoint
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _get(http: aiohttp.ClientSession, path: str) -> dict | None:
    url = f"{config.DEXSCREENER_BASE}{path}"
    try:
        async with http.get(url, timeout=_TIMEOUT) as resp:
            if resp.status == 429:
                logger.warning("DexScreener 429, backoff")
                await asyncio.sleep(3)
                return None
            if resp.status != 200:
                logger.warning("DexScreener %s -> HTTP %s", path, resp.status)
                return None
            return await resp.json()
    except Exception as e:
        logger.error("DexScreener request error %s: %s", path, e)
        return None


def _best_pair(data: dict | None, mint: str) -> dict | None:
    """Пара этого mint с максимальной ликвидностью на Solana.

    Мусорные пулы с неверной ценой раздувают liquidity.usd в тысячи раз
    (наблюдалось: GALA-пул с ценой $10.42 при реальной $0.0021 → «$190M
    ликвидности»). Пулы, чья цена отклоняется от медианы >3×, отбрасываются.
    """
    if not data:
        return None
    pairs = [
        p for p in (data.get("pairs") or [])
        if p.get("chainId") == "solana"
        and (p.get("baseToken") or {}).get("address") == mint
    ]
    if not pairs:
        return None

    prices = sorted(float(p["priceUsd"]) for p in pairs if p.get("priceUsd"))
    if prices:
        median = prices[len(prices) // 2]
        sane = [
            p for p in pairs
            if not p.get("priceUsd")
            or (median / 3 <= float(p["priceUsd"]) <= median * 3)
        ]
        if sane:
            pairs = sane
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


def _pair_to_market(pair: dict | None) -> dict | None:
    """Нормализация к формату, который ест risk_engine.evaluate()."""
    if not pair:
        return None
    created_ms = pair.get("pairCreatedAt")
    return {
        "price_usd": float(pair["priceUsd"]) if pair.get("priceUsd") else None,
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
        "volume_h24": (pair.get("volume") or {}).get("h24"),
        "market_cap": pair.get("marketCap") or pair.get("fdv"),
        "price_change_h24": (pair.get("priceChange") or {}).get("h24"),
        "pair_created_at": (
            datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
            if created_ms else None
        ),
        "dex_id": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "symbol": (pair.get("baseToken") or {}).get("symbol"),
        "name": (pair.get("baseToken") or {}).get("name"),
    }


async def get_market(http: aiohttp.ClientSession, mint: str) -> dict | None:
    """Живая выборка рынка для одного mint (для /check)."""
    data = await _get(http, f"/latest/dex/tokens/{mint}")
    return _pair_to_market(_best_pair(data, mint))


def apply_market_to_token(token: Token, market: dict | None) -> None:
    """Обновить денормализованные поля токена (наивный UTC, как в БД).

    У каталожных токенов (есть coingecko_id) цена/капа/объём/изменение приходят
    из CoinGecko при синке каталога — тонкие солановые пулы DexScreener дают
    мусорные значения. DexScreener пишет только Solana-специфику.
    """
    now = datetime.utcnow()
    is_cg = bool(token.coingecko_id)
    if market:
        token.liquidity_usd = market["liquidity_usd"]
        pca = market["pair_created_at"]
        token.pair_created_at = pca.replace(tzinfo=None) if pca else None
        token.dex_id = market["dex_id"]
        token.pair_address = market["pair_address"]
        if not is_cg:
            token.price_usd = market["price_usd"]
            token.volume_h24 = market["volume_h24"]
            token.market_cap = market["market_cap"]
            token.price_change_h24 = market["price_change_h24"]
        if not token.symbol and market["symbol"]:
            token.symbol = market["symbol"]
        if not token.name and market["name"]:
            token.name = market["name"]
    else:
        token.liquidity_usd = None
        if not is_cg:
            token.price_usd = None
            token.volume_h24 = None
    token.metrics_updated_at = now


async def run_dexscreener_sync(db: AsyncSession) -> list[Token]:
    """Обновить метрики всех watched-токенов + записать снапшоты.

    Возвращает обновлённые токены (для пересчёта риска и алертов).
    """
    result = await db.execute(select(Token).where(Token.watched.is_(True)))
    tokens = list(result.scalars().all())
    if not tokens:
        return []

    updated: list[Token] = []
    async with aiohttp.ClientSession() as http:
        for token in tokens:
            market = await get_market(http, token.mint)
            apply_market_to_token(token, market)
            db.add(TokenSnapshot(
                token_id=token.id,
                price_usd=token.price_usd,
                liquidity_usd=token.liquidity_usd,
                volume_h24=token.volume_h24,
                market_cap=token.market_cap,
            ))
            updated.append(token)
            await asyncio.sleep(_REQUEST_DELAY)

    await db.commit()
    logger.info("DexScreener sync: %d watched tokens updated", len(updated))
    return updated
