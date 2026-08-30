"""solgames.buzz — каталог игр на Solana (основной источник радара).

HTML сайта закрыт Cloudflare JS-challenge, но JSON API открыт без ключа:
    GET /api/projects?limit=500  -> {projects: [...], total, counts, stageCounts}
    GET /api/projects/{slug}     -> {project: {...}}

Отдаёт только Solana-native игры, проверенные их AI-агентом: есть играбельный
клиент, подтверждённая дата запуска, резолвнутый токен. Это именно то, чего
не даёт CoinGecko (там в категорию gaming лезут мосты и мемкоины).
"""
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import Game

logger = logging.getLogger(__name__)

# httpx, а не aiohttp: на ответах solgames >~35 КБ aiohttp 3.9 виснет
# посреди чанкед-стрима (Caddy за Cloudflare), curl/requests/httpx — нет.
_TIMEOUT = 30.0
_PAGE_LIMIT = 500
# Cloudflare перед solgames режет дефолтный python-UA (в GitHub Actions — сразу 403),
# поэтому ходим с обычными браузерными заголовками
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://solgames.buzz/discover",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Запасной путь, когда Cloudflare режет прямой запрос (см. _get_via_reader)
_READER_BASE = "https://r.jina.ai/"
_READER_TIMEOUT = 90.0
used_reader = False  # True, если в этом процессе хоть раз пришлось идти через ридер

# Статусы проекта в solgames: rejected/inactive нас не интересуют
ACTIVE_STATUSES = {"enriched", "new", "verified"}


def _jload(value, default):
    """Часть полей API приходит JSON-строкой, часть — уже структурой."""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _dt(value) -> datetime | None:
    """ISO-строка любого вида -> наивный UTC datetime (как хранит БД)."""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (parsed.astimezone(timezone.utc).replace(tzinfo=None)
            if parsed.tzinfo else parsed)


def _num(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize(p: dict) -> dict | None:
    """Проект solgames -> плоская запись игры. None = не наш случай."""
    slug = p.get("slug")
    if not slug or p.get("project_type") != "game":
        return None
    if p.get("status") not in ACTIVE_STATUSES or p.get("inactive"):
        return None

    links = _jload(p.get("links"), {})
    tags = [t for t in _jload(p.get("tags"), []) if isinstance(t, str)]
    handle = p.get("twitter_handle")
    shot = p.get("screenshot_path")  # screenshots/28.png
    token_mint = p.get("token_mint") or None
    market_cap = _num(p.get("token_market_cap"))
    liquidity = _num(p.get("token_liquidity_usd"))
    # token_status в solgames ненадёжен (у половины торгуемых пар стоит "none"),
    # поэтому «торгуется» = есть mint и по нему пришли рыночные данные
    tradeable = bool(token_mint) and bool(market_cap or liquidity)

    return {
        "slug": slug,
        "solgames_id": p.get("id"),
        "name": p.get("name") or p.get("title") or slug,
        "tagline": p.get("tagline") or p.get("description"),
        "description": p.get("description"),
        "genre": p.get("genre"),
        "tags": tags,
        "url": p.get("url") or links.get("website"),
        "twitter": f"https://x.com/{handle}" if handle else None,
        "solgames_url": f"https://solgames.buzz/game/{slug}",
        "image_url": (f"https://solgames.buzz/api/{shot}" if shot
                      else p.get("twitter_avatar")),
        "launch_date": p.get("launch_date"),
        "launch_stage": p.get("launch_stage"),
        "launch_access": p.get("launch_access"),
        "status": p.get("status"),
        "buzz_score": _num(p.get("buzz_score")),
        "buzz_delta_24h": _num(p.get("buzz_delta_24h")),
        "live_online": p.get("live_online"),
        "mention_count": p.get("mention_count"),
        "twitter_followers": p.get("twitter_followers"),
        "token_mint": token_mint,
        "token_symbol": (p.get("token_symbol") or "").upper() or None,
        "token_tradeable": tradeable,
        "price_usd": _num(p.get("token_price_usd")),
        "price_change_h24": _num(p.get("token_price_change_24h")),
        "market_cap": market_cap,
        "liquidity_usd": liquidity,
        "volume_h24": _num(p.get("token_volume_24h")),
        "ath_market_cap": _num(p.get("ath_market_cap")),
        "mcap_delta_24h": _num(p.get("mcap_delta_24h")),
        "pair_created_at": _dt(p.get("token_pair_created_at")),
        "source_first_seen_at": _dt(p.get("first_seen_at")),
        "source_updated_at": _dt(p.get("updated_at")),
    }


def to_market(game) -> dict | None:
    """Игра (ORM-объект или dict из normalize) -> market-словарь для risk_engine.

    Данные о рынке уже есть в самом каталоге solgames, отдельный запрос
    в DexScreener ради тех же цифр не нужен.
    """
    get = game.get if isinstance(game, dict) else lambda k: getattr(game, k, None)
    if not get("token_mint") or not get("token_tradeable"):
        return None
    mcap, ath = get("market_cap"), get("ath_market_cap")
    return {
        "price_usd": get("price_usd"),
        "liquidity_usd": get("liquidity_usd"),
        "volume_h24": get("volume_h24"),
        "market_cap": mcap,
        "price_change_h24": get("price_change_h24"),
        "pair_created_at": get("pair_created_at"),
        # ath_change_pct считаем по капитализации: цена ATH в solgames не хранится
        "ath_change_pct": ((mcap / ath - 1) * 100 if mcap and ath and ath > 0 else None),
    }


async def _get_direct(url: str, params: dict | None) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS,
                                     follow_redirects=True) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning("solgames %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.error("solgames %s error: %s", url, e)
        return None


async def _get_via_reader(url: str, params: dict | None) -> dict | None:
    """Обход через r.jina.ai: Cloudflare отдаёт 403 на IP дата-центров (GitHub Actions).

    Ридер возвращает текст вида "Title: …\n\nURL Source: …\n\nMarkdown Content:\n{json}",
    поэтому JSON вырезаем от первой фигурной скобки до конца.
    """
    full = url + (("?" + urlencode(params)) if params else "")
    try:
        async with httpx.AsyncClient(timeout=_READER_TIMEOUT,
                                     follow_redirects=True) as client:
            resp = await client.get(_READER_BASE + full)
        if resp.status_code != 200:
            logger.warning("solgames reader %s -> HTTP %s", full, resp.status_code)
            return None
        start = resp.text.find("{")
        if start < 0:
            return None
        data = json.loads(resp.text[start:])
    except Exception as e:
        logger.error("solgames reader %s error: %s", full, e)
        return None
    global used_reader
    used_reader = True
    return data


async def _get_json(path: str, params: dict | None = None) -> dict | None:
    url = f"{config.SOLGAMES_BASE}{path}"
    data = await _get_direct(url, params)
    if data is None:
        data = await _get_via_reader(url, params)
    return data


async def fetch_games() -> list[dict] | None:
    """Все активные игры каталога. None = источник недоступен (синк пропускаем)."""
    data = await _get_json("/api/projects", {"limit": _PAGE_LIMIT})
    projects = data.get("projects") if isinstance(data, dict) else None
    if not projects:
        logger.warning("solgames: пустой ответ")
        return None
    games = [g for g in (normalize(p) for p in projects) if g]
    logger.info("solgames: %d активных игр из %d проектов", len(games), len(projects))
    return games


async def fetch_game(slug: str) -> dict | None:
    """Детали одной игры: в списочном ответе нет полного about."""
    data = await _get_json(f"/api/projects/{slug}")
    project = data.get("project") if isinstance(data, dict) else None
    if not project:
        return None
    row = normalize(project)
    if row:
        row["about"] = project.get("about")
    return row


_FIELDS = (
    "solgames_id", "name", "tagline", "description", "genre", "tags", "url",
    "twitter", "solgames_url", "image_url", "launch_date", "launch_stage",
    "launch_access", "status", "buzz_score", "buzz_delta_24h", "live_online",
    "mention_count", "twitter_followers", "token_mint", "token_symbol",
    "token_tradeable", "price_usd", "price_change_h24", "market_cap",
    "liquidity_usd", "volume_h24", "ath_market_cap", "mcap_delta_24h",
    "pair_created_at", "source_first_seen_at", "source_updated_at",
)


async def run_games_sync(db: AsyncSession) -> list[Game]:
    """Синк каталога игр. Возвращает НОВЫЕ игры (для алертов).

    Первый сид возвращает [] — иначе бот выстрелит 180 сообщениями подряд.
    Пропавшие из выдачи игры не удаляются, а помечаются inactive: solgames
    переводит проекты в rejected/inactive, а историю первого показа терять жаль.
    """
    existing = {
        g.slug: g for g in (await db.execute(select(Game))).scalars().all()
    }
    is_first_seed = not existing

    games = await fetch_games()
    if games is None:
        logger.warning("Games sync пропущен: solgames недоступен")
        return []

    now = datetime.utcnow()
    new_games: list[Game] = []
    seen: set[str] = set()
    for row in games:
        slug = row["slug"]
        seen.add(slug)
        game = existing.get(slug)
        if game is None:
            game = Game(slug=slug, first_seen_at=now)
            db.add(game)
            new_games.append(game)
        for field in _FIELDS:
            setattr(game, field, row[field])
        game.inactive = False
        game.last_seen_at = now

    gone = 0
    for slug, game in existing.items():
        if slug not in seen and not game.inactive:
            game.inactive = True
            gone += 1

    await db.commit()
    logger.info("Games sync: %d всего, %d новых, %d выбыло (first_seed=%s)",
                len(games), len(new_games), gone, is_first_seed)
    return [] if is_first_seed else new_games
