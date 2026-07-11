"""CoinGecko: каталог P2E/gaming токенов на Solana с mint-адресами.

Два запроса: /coins/list?include_platform=true (тяжёлый, кэш 24ч в модуле)
+ /coins/markets?category=... Пересечение даёт Solana-токены категории с mint.
Проверено 09.07.2026: категория play-to-earn ∩ solana = ~42 токена.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import Token

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 12.0  # keyless CoinGecko: ~5 req/min с учётом тяжёлого coins/list
_TIMEOUT = aiohttp.ClientTimeout(total=60)  # coins/list весит несколько МБ

CATEGORIES = ["play-to-earn", "gaming", "on-chain-gaming",
              "massively-multiplayer-online-mmo"]
# Категории CoinGecko грязные: мемкоины и DePIN вписывают себе "gaming".
# Токен, состоящий в любой из этих категорий, из каталога исключается.
EXCLUDE_CATEGORIES = ["meme-token", "solana-meme-coins", "depin"]

# Ручной чёрный список: mint сюда — и токен никогда не попадёт в каталог
# (и будет удалён из него при следующем синке, если не стоит в вотчлисте)
BLACKLIST_MINTS = {
    "PLAYs3GSSadH2q2JLS7djp7yzeT75NK78XgrE5YLrfq",  # Play Solana: -95% после TGE, объём $700/день
}

# Категорийная выдача keyless CoinGecko нестабильна (утром 100+ монет, вечером 33),
# а /coins/list временами приходит урезанным. Известные игры на Solana подтягиваются
# по id всегда, с захардкоженными mint (SPL-mint неизменен по определению).
SEED_MINTS = {
    "aurory": "AURYydfxJib1ZkTir1Jn1J9ECYUtjb6rKQVmtYaixWPP",
    "stepn": "7i5KKsX2weiTkry7jA4ZwSuXGhs5eJBEjY8vVxR4pfRx",
    "green-satoshi-token": "AFbX8oGjGpmVFywbVouvhQSRmiW2aR1mohfahi4Y2AdB",
    "deapcoin": "BgwQjVNMWvt2d8CN51CsbniwRWyZ9H9HfHkEsvikeVuZ",
    "tower": "5Ro9KjSUGYisjREz8K5uD1fMdXnu1Jfq3Ktqm4EQMc1R",
    "gunz": "3jUf2RTyXp867piSB2dt8uUcNiLDW58asjGtXkRAkBbe",
    "wilder-world": "FVvd3s9dZYzsgitkJyWbmycSc8MkYZjyF7oqAEvmSxTZ",
    "mecca": "mecySk7eSawDNfAXvW3CquhLyxyKaXExFXgUUbEZE1T",
    "idlemine": "BjcRmwm8e25RgjkyaFE56fc7bxRgGPw96JUkXRJFEroT",
    "mimbogamegroup": "JBQXZYo1PAKQkePTZerBmMU5ujcMm177wyyQza8S8gNg",
    "moonwalk-fitness": "moonThZEkkTVoNB7v6YVCQiT56JYDZ1oN185ba3WizL",
}

# Кэш mint-маппинга: {coingecko_id: solana_mint}
_PLATFORMS_CACHE: dict[str, str] = {}
_PLATFORMS_CACHE_TS: float = 0.0
_PLATFORMS_TTL = 24 * 3600


async def _get(http: aiohttp.ClientSession, path: str, params: dict | None = None,
               retries: int = 3) -> list | dict | None:
    url = f"{config.COINGECKO_BASE}{path}"
    for attempt in range(retries):
        try:
            async with http.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status == 429:
                    wait = 35 * (attempt + 1)
                    logger.warning("CoinGecko 429, backoff %ss (attempt %d/%d)",
                                   wait, attempt + 1, retries)
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    logger.warning("CoinGecko %s -> HTTP %s", path, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.error("CoinGecko error %s: %s", path, e)
            return None
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
    # CoinGecko временами отдаёт урезанный список — не затираем хороший кэш худшим
    if _PLATFORMS_CACHE and len(mapping) < len(_PLATFORMS_CACHE) * 0.8:
        logger.warning("CoinGecko platforms shrank (%d -> %d), keeping old cache",
                       len(_PLATFORMS_CACHE), len(mapping))
        _PLATFORMS_CACHE_TS = time.time()
        return _PLATFORMS_CACHE
    _PLATFORMS_CACHE = mapping
    _PLATFORMS_CACHE_TS = time.time()
    logger.info("CoinGecko platforms cache: %d solana coins", len(mapping))
    return mapping


async def _category_ids(http: aiohttp.ClientSession, category: str) -> set[str] | None:
    """Множество coingecko_id токенов категории (для исключений). None = не скачалось."""
    coins = await _get(http, "/api/v3/coins/markets", {
        "vs_currency": "usd", "category": category,
        "order": "market_cap_desc", "per_page": "250", "page": "1",
    })
    return {c["id"] for c in coins} if isinstance(coins, list) else None


async def fetch_catalog_coins(http: aiohttp.ClientSession) -> list[dict] | None:
    """Игровые Solana-токены: {id, mint, symbol, name, image, categories, market data}.

    Общая логика для синка в БД и статического экспорта (GitHub Pages).
    None = данные неполные (какая-то категория не скачалась) — синк надо пропустить,
    иначе зачистка каталога снесёт живые токены.
    """
    mints = await _solana_mints(http)
    if not mints:
        return None

    excluded: set[str] = set()
    for category in EXCLUDE_CATEGORIES:
        await asyncio.sleep(_REQUEST_DELAY)
        ids = await _category_ids(http, category)
        if ids is None:
            logger.warning("Catalog fetch incomplete: exclude category %s failed", category)
            return None
        excluded |= ids

    rows: dict[str, dict] = {}

    def _add(coin: dict, category: str) -> None:
        cid = coin["id"]
        mint = mints.get(cid) or SEED_MINTS.get(cid)
        if not mint or cid in excluded or mint in BLACKLIST_MINTS:
            return
        if cid in rows:
            if category not in rows[cid]["categories"]:
                rows[cid]["categories"].append(category)
            return
        rows[cid] = {
            "id": cid,
            "mint": mint,
            "symbol": (coin.get("symbol") or "").upper() or None,
            "name": coin.get("name"),
            "image": coin.get("image"),
            "categories": [category],
            "market_cap": coin.get("market_cap"),
            "current_price": coin.get("current_price"),
            "total_volume": coin.get("total_volume"),
            "price_change_percentage_24h": coin.get("price_change_percentage_24h"),
        }

    for category in CATEGORIES:
        await asyncio.sleep(_REQUEST_DELAY)
        coins = await _get(http, "/api/v3/coins/markets", {
            "vs_currency": "usd", "category": category,
            "order": "market_cap_desc", "per_page": "250", "page": "1",
        })
        if not isinstance(coins, list):
            logger.warning("Catalog fetch incomplete: category %s failed", category)
            return None
        for coin in coins:
            _add(coin, category)

    # Seed-игры по id — страховка от дырявой категорийной выдачи
    await asyncio.sleep(_REQUEST_DELAY)
    seeds = await _get(http, "/api/v3/coins/markets", {
        "vs_currency": "usd", "ids": ",".join(SEED_MINTS), "per_page": "250",
    })
    if isinstance(seeds, list):
        for coin in seeds:
            _add(coin, "play-to-earn")

    return list(rows.values())


DETAILS_PER_SYNC = 10  # обогащений (сайт/соцсети/описание) за один прогон


async def fetch_coin_details(http: aiohttp.ClientSession, cid: str) -> dict | None:
    """Ссылки на игру и описание из /coins/{id}. None = не скачалось."""
    data = await _get(http, f"/api/v3/coins/{cid}", {
        "localization": "true", "tickers": "false", "market_data": "false",
        "community_data": "false", "developer_data": "false", "sparkline": "false",
    })
    if not isinstance(data, dict):
        return None
    links = data.get("links") or {}
    desc = data.get("description") or {}
    text = (desc.get("ru") or desc.get("en") or "").strip()
    if len(text) > 600:
        text = text[:600].rsplit(" ", 1)[0] + "…"
    homepage = next((u for u in (links.get("homepage") or []) if u), None)
    chat_urls = [u for u in (links.get("chat_url") or []) if u]
    twitter = links.get("twitter_screen_name")
    return {
        "description": text or None,
        "links": {
            "homepage": homepage,
            "twitter": f"https://x.com/{twitter}" if twitter else None,
            "telegram": (f"https://t.me/{links['telegram_channel_identifier']}"
                         if links.get("telegram_channel_identifier") else None),
            "discord": next((u for u in chat_urls if "discord" in u), None),
        },
    }


async def run_catalog_sync(db: AsyncSession) -> list[Token]:
    """Синк каталога. Возвращает список НОВЫХ токенов (для алертов).

    Если таблица была пуста (первый сид) — вернёт [], чтобы не заспамить алертами.
    Каталожные токены, выпавшие из каталога (мемкоины и т.п.), удаляются,
    если не стоят в вотчлисте.
    """
    existing_result = await db.execute(select(Token.mint))
    existing_mints = {m for (m,) in existing_result.all()}
    is_first_seed = not existing_mints

    async with aiohttp.ClientSession() as http:
        coins = await fetch_catalog_coins(http)
    if coins is None:
        logger.warning("CoinGecko catalog sync skipped: incomplete data")
        return []

    now = datetime.utcnow()
    new_tokens: list[Token] = []
    for coin in coins:
        mint = coin["mint"]
        if mint in existing_mints:
            result = await db.execute(select(Token).where(Token.mint == mint))
            token = result.scalar_one_or_none()
            if token:
                token.categories = coin["categories"]
                token.last_seen_at = now
                if not token.image_url:
                    token.image_url = coin["image"]
                # CG — источник цены/капы для каталожных токенов (см. dexscreener.py)
                token.price_usd = coin["current_price"]
                token.market_cap = coin["market_cap"]
                token.volume_h24 = coin["total_volume"]
                token.price_change_h24 = coin["price_change_percentage_24h"]
                token.metrics_updated_at = now
            continue
        token = Token(
            mint=mint,
            symbol=coin["symbol"],
            name=coin["name"],
            source="catalog",
            coingecko_id=coin["id"],
            image_url=coin["image"],
            categories=coin["categories"],
            market_cap=coin["market_cap"],
            price_usd=coin["current_price"],
            volume_h24=coin["total_volume"],
            price_change_h24=coin["price_change_percentage_24h"],
            metrics_updated_at=now,
            last_seen_at=now,
        )
        db.add(token)
        existing_mints.add(mint)
        new_tokens.append(token)

    # Обогащение ссылками на игру (сайт/соцсети/описание) — порциями,
    # чтобы не выжигать лимиты; за несколько прогонов покрывается весь каталог
    need_details = await db.execute(
        select(Token).where(
            Token.source == "catalog",
            Token.coingecko_id.isnot(None),
            Token.links.is_(None),
        ).limit(DETAILS_PER_SYNC))
    async with aiohttp.ClientSession() as http:
        for token in need_details.scalars().all():
            await asyncio.sleep(_REQUEST_DELAY)
            details = await fetch_coin_details(http, token.coingecko_id)
            if details:
                token.links = details["links"]
                token.description = details["description"]

    # Зачистка: «долго не виденные» (категорийная выдача CoinGecko дырявая,
    # разовый пропуск — не повод удалять) + чёрный список
    week_ago = now - timedelta(days=7)
    stale = await db.execute(
        select(Token).where(
            Token.source == "catalog",
            Token.watched.is_(False),
            ((Token.last_seen_at.isnot(None)) & (Token.last_seen_at < week_ago))
            | Token.mint.in_(BLACKLIST_MINTS),
        ))
    removed = 0
    for token in stale.scalars().all():
        await db.delete(token)
        removed += 1

    await db.commit()
    logger.info("Catalog sync: %d new, %d removed (first_seed=%s)",
                len(new_tokens), removed, is_first_seed)
    return [] if is_first_seed else new_tokens
