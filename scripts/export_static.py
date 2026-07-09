"""Экспорт статического сайта для GitHub Pages.

Запускается в GitHub Actions по крону. Не использует БД — собирает данные
напрямую из API и пишет JSON в _site/data/ + копирует дашборд.

Бюджет времени CI: ~90 сек. Полная проверка риска (DexScreener + RugCheck) —
только для вотчлиста (watchlist.json) и топ-N каталога по market cap.
"""
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import aiohttp  # noqa: E402

from analyzer.risk_engine import evaluate  # noqa: E402
from collectors import coingecko  # noqa: E402
from collectors.dexscreener import get_market  # noqa: E402
from collectors.onchain import get_security  # noqa: E402

SITE_DIR = BASE_DIR / "_site"
DATA_DIR = SITE_DIR / "data"
TOP_N_FULL_CHECK = 20  # сколько топ-токенов каталога проверять полностью
CHECK_DELAY = 1.0      # пауза между полными проверками (rate limits)


def _dt_iso(v) -> str | None:
    return v.isoformat() if v else None


async def _prev_catalog(http: aiohttp.ClientSession) -> list[dict]:
    """Прошлый catalog.json с живого сайта — память между запусками CI.

    CoinGecko keyless временами отдаёт урезанные ответы; union со вчерашним
    каталогом сглаживает провалы. Записи старше 7 дней отбрасываются.
    """
    url = os.environ.get("PREV_CATALOG_URL")
    if not url:
        return []
    try:
        async with http.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return []
            prev = await resp.json()
    except Exception:
        return []
    week_ago = datetime.now(timezone.utc).timestamp() - 7 * 86400
    fresh = []
    for row in prev if isinstance(prev, list) else []:
        ts = row.get("metrics_updated_at")
        try:
            if ts and datetime.fromisoformat(ts).timestamp() >= week_ago:
                fresh.append(row)
        except ValueError:
            continue
    return fresh


async def fetch_catalog(http: aiohttp.ClientSession) -> list[dict]:
    """Каталог P2E×Solana из CoinGecko (без БД) — через общий фильтр коллектора."""
    coins = await coingecko.fetch_catalog_coins(http)
    if not coins:
        raise RuntimeError("CoinGecko catalog fetch failed")
    rows = [{
        "mint": c["mint"],
        "symbol": c["symbol"],
        "name": c["name"],
        "source": "catalog",
        "coingecko_id": c["id"],
        "image_url": c["image"],
        "categories": c["categories"],
        "watched": False,
        "price_usd": c["current_price"],
        "liquidity_usd": None,
        "volume_h24": c["total_volume"],
        "market_cap": c["market_cap"],
        "price_change_h24": c["price_change_percentage_24h"],
        "pair_created_at": None, "dex_id": None,
        "risk_score": None, "risk_level": None, "risk_flags": [],
        "metrics_updated_at": datetime.now(timezone.utc).isoformat(),
        "first_seen_at": None,
    } for c in coins]

    # Union с прошлым каталогом сайта: свежие данные приоритетнее
    by_mint = {r["mint"]: r for r in await _prev_catalog(http)}
    by_mint.update({r["mint"]: r for r in rows})
    return sorted(by_mint.values(), key=lambda r: r["market_cap"] or 0, reverse=True)


async def full_check(http: aiohttp.ClientSession, row: dict) -> dict:
    """Полная проверка: DexScreener + RugCheck/RPC + risk engine. Обновляет row."""
    mint = row["mint"]
    market = await get_market(http, mint)
    security = await get_security(http, mint)

    # Для каталожных токенов риск считается от честных агрегатных данных CG
    # + солановой ликвидности DexScreener (мусорные цены пулов не подмешиваем)
    eval_market = market
    if market and row.get("coingecko_id"):
        eval_market = {
            **market,
            "market_cap": row.get("market_cap"),
            "volume_h24": row.get("volume_h24"),
            "price_change_h24": row.get("price_change_h24"),
        }
    report = evaluate(eval_market, security, mint)

    is_cg = bool(row.get("coingecko_id"))
    if market:
        # У каталожных токенов цена/капа/изменение — из CoinGecko (агрегат бирж):
        # тонкие солановые пулы дают мусор ($516B fdv, +513779%). DexScreener
        # здесь источник только Solana-специфики: ликвидность, DEX, возраст пары.
        row.update({
            "liquidity_usd": market["liquidity_usd"],
            "pair_created_at": _dt_iso(market["pair_created_at"]),
            "dex_id": market["dex_id"],
        })
        if not is_cg:
            row.update({
                "price_usd": market["price_usd"],
                "volume_h24": market["volume_h24"],
                "market_cap": market["market_cap"],
                "price_change_h24": market["price_change_h24"],
            })
        row["symbol"] = row.get("symbol") or market["symbol"]
        row["name"] = row.get("name") or market["name"]
    row["risk_score"] = report.score
    row["risk_level"] = report.level
    row["risk_flags"] = [f.as_dict() for f in report.flags]

    # Файл деталей для клика по строке
    detail = {
        **row,
        "security": security and {
            "mint_authority_active": security["mint_authority_active"],
            "freeze_authority_active": security["freeze_authority_active"],
            "top10_holder_pct": security["top10_holder_pct"],
            "lp_locked_pct": security["lp_locked_pct"],
            "rugcheck_score": security["rugcheck_score"],
            "holders_count": security["holders_count"],
            "source": security["source"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
        "snapshots": [],
    }
    (DATA_DIR / "tokens").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "tokens" / f"{mint}.json").write_text(
        json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return row


async def main() -> None:
    shutil.rmtree(SITE_DIR, ignore_errors=True)
    DATA_DIR.mkdir(parents=True)

    watchlist_mints: list[str] = json.loads(
        (BASE_DIR / "watchlist.json").read_text(encoding="utf-8"))["mints"]

    async with aiohttp.ClientSession() as http:
        catalog = await fetch_catalog(http)
        by_mint = {r["mint"]: r for r in catalog}

        # Вотчлист: полная проверка каждого mint
        watch_rows = []
        for mint in watchlist_mints:
            row = by_mint.get(mint) or {
                "mint": mint, "symbol": None, "name": None, "source": "manual",
                "coingecko_id": None, "categories": [], "watched": True,
                "market_cap": None, "risk_flags": [],
                "first_seen_at": None, "metrics_updated_at": None,
            }
            row["watched"] = True
            await asyncio.sleep(CHECK_DELAY)
            watch_rows.append(await full_check(http, row))

        # Топ каталога: полная проверка (риск-бейджи на сайте)
        checked = 0
        for row in catalog:
            if row["watched"] or checked >= TOP_N_FULL_CHECK:
                continue
            await asyncio.sleep(CHECK_DELAY)
            await full_check(http, row)
            checked += 1

    watch_rows.sort(key=lambda r: r["risk_score"] or 0, reverse=True)
    (DATA_DIR / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "tokens.json").write_text(
        json.dumps(watch_rows, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "alerts.json").write_text("[]", encoding="utf-8")
    (DATA_DIR / "stats.json").write_text(json.dumps({
        "catalog_total": len(catalog),
        "watched": len(watch_rows),
        "watched_high_risk": sum(1 for r in watch_rows if r["risk_level"] == "high"),
        "alerts_24h": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")

    shutil.copy(BASE_DIR / "web" / "index.html", SITE_DIR / "index.html")
    print(f"OK: {len(catalog)} catalog, {len(watch_rows)} watched, "
          f"{checked} top checked -> {SITE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
