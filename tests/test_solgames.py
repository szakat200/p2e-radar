from datetime import datetime

from collectors.solgames import _dt, _jload, normalize, to_market

# Урезанный ответ /api/projects (поля-строки — как их реально отдаёт API)
KINTARA = {
    "id": 28, "slug": "kintara", "name": "Kintara", "title": "Kintara",
    "project_type": "game", "status": "enriched", "inactive": 0,
    "description": "Isometric play-to-earn MMO on Solana.",
    "tagline": "Gather, fight, trade, cash out in $KINS.",
    "genre": "mmo", "tags": '["mmo","pvp","solana"]',
    "links": '{"website":"https://kintara.com"}', "url": "https://kintara.gg",
    "twitter_handle": "PlayKintara", "twitter_followers": 18885,
    "screenshot_path": "screenshots/28.png",
    "launch_date": "2026-05-22", "launch_stage": "mainnet", "launch_access": "open",
    "buzz_score": 0, "buzz_delta_24h": 0, "live_online": 505, "mention_count": 72640,
    "token_mint": "Tqj8yFmagrg7oorpQkVGYR52r96RFTamvWfth9bpump",
    "token_symbol": "kins", "token_status": "tradeable",
    "token_price_usd": 0.002518, "token_price_change_24h": -18,
    "token_market_cap": 2497799, "token_liquidity_usd": 249085.4,
    "token_volume_24h": 192001.02, "ath_market_cap": 21305034,
    "token_pair_created_at": "2026-05-22T17:47:23.000Z",
    "first_seen_at": "2026-06-15 17:17:56.648615+00",
    "updated_at": "2026-08-30 04:04:57.112677+00",
}


def test_normalize_parses_string_fields():
    game = normalize(KINTARA)
    assert game["slug"] == "kintara"
    assert game["tags"] == ["mmo", "pvp", "solana"]
    assert game["token_symbol"] == "KINS"          # тикер приводится к верхнему регистру
    assert game["twitter"] == "https://x.com/PlayKintara"
    assert game["image_url"] == "https://solgames.buzz/api/screenshots/28.png"
    assert game["solgames_url"] == "https://solgames.buzz/game/kintara"
    assert game["pair_created_at"] == datetime(2026, 5, 22, 17, 47, 23)


def test_normalize_skips_rejected_and_non_games():
    assert normalize({**KINTARA, "status": "rejected"}) is None
    assert normalize({**KINTARA, "inactive": 1}) is None
    assert normalize({**KINTARA, "project_type": "tool"}) is None
    assert normalize({**KINTARA, "slug": None}) is None


def test_tradeable_ignores_unreliable_token_status():
    # У половины реально торгуемых пар solgames проставляет token_status="none",
    # поэтому решают рыночные данные, а не статус
    game = normalize({**KINTARA, "token_status": "none"})
    assert game["token_tradeable"] is True

    no_market = normalize({**KINTARA, "token_market_cap": None,
                           "token_liquidity_usd": None})
    assert no_market["token_tradeable"] is False

    no_token = normalize({**KINTARA, "token_mint": None, "token_symbol": None})
    assert no_token["token_tradeable"] is False


def test_to_market_computes_ath_drop():
    market = to_market(normalize(KINTARA))
    assert market["liquidity_usd"] == 249085.4
    # -88% от пика капитализации
    assert -89 < market["ath_change_pct"] < -87


def test_to_market_none_without_tradeable_token():
    assert to_market(normalize({**KINTARA, "token_mint": None})) is None


def test_jload_and_dt_tolerate_garbage():
    assert _jload("not json", []) == []
    assert _jload(None, {}) == {}
    assert _jload(["already", "list"], []) == ["already", "list"]
    assert _dt("") is None
    assert _dt("не дата") is None
    # смещение убирается — в БД всё хранится наивным UTC
    assert _dt("2026-08-30T04:04:57Z") == datetime(2026, 8, 30, 4, 4, 57)
