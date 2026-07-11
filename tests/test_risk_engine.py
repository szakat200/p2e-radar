from datetime import datetime, timedelta, timezone

from analyzer.risk_engine import evaluate

RELIC_MINT = "2ABbnf3EzGfiMa3PE2bseAWwRD4jAE4KgE8YjSTxpump"


def _old_pair():
    return datetime.now(timezone.utc) - timedelta(days=400)


def test_healthy_token_low_risk():
    market = {
        "price_usd": 1.2, "liquidity_usd": 2_000_000, "volume_h24": 5_000_000,
        "market_cap": 50_000_000, "price_change_h24": 3.5, "pair_created_at": _old_pair(),
    }
    security = {
        "mint_authority_active": False, "freeze_authority_active": False,
        "top10_holder_pct": 20.0, "lp_locked_pct": 100.0,
    }
    report = evaluate(market, security, "So11111111111111111111111111111111111111112")
    assert report.level == "low"
    assert report.score < 30
    reds = [f for f in report.flags if f.severity != "good"]
    greens = {f.code for f in report.flags if f.severity == "good"}
    assert reds == []
    # здоровый токен собирает зелёные флаги
    assert "AUTHORITIES_REVOKED" in greens
    assert "LP_LOCKED" in greens
    assert "DISTRIBUTED_SUPPLY" in greens
    assert "MATURE_PAIR" in greens
    assert "ACTIVE_MARKET" in greens


def test_relic_like_token_high_risk():
    # Профиль реального RELIC: liq $8.6K, объём $10K, mcap $13.6K, pump-суффикс
    market = {
        "price_usd": 0.0000136, "liquidity_usd": 8_670, "volume_h24": 10_334,
        "market_cap": 13_607, "price_change_h24": -0.83, "pair_created_at": _old_pair(),
    }
    security = {
        "mint_authority_active": False, "freeze_authority_active": False,
        "top10_holder_pct": 79.0, "lp_locked_pct": 0.0,
    }
    report = evaluate(market, security, RELIC_MINT)
    assert report.level == "high"
    assert report.score >= 60
    codes = report.flag_codes()
    assert "LIQ_CRITICAL" in codes
    assert "TOP10_HEAVY" in codes
    assert "LP_UNLOCKED" in codes
    assert "PUMPFUN_ORIGIN" in codes
    assert "MCAP_MICRO" in codes


def test_none_inputs_no_crash():
    report = evaluate(None, None, RELIC_MINT)
    codes = report.flag_codes()
    assert "NO_PAIR" in codes
    assert "NO_ONCHAIN_DATA" in codes
    assert "PUMPFUN_ORIGIN" in codes
    assert report.level == "medium"  # 40+5+5 = 50


def test_mint_authority_is_critical():
    market = {
        "price_usd": 0.5, "liquidity_usd": 500_000, "volume_h24": 100_000,
        "market_cap": 10_000_000, "price_change_h24": 0.0, "pair_created_at": _old_pair(),
    }
    security = {
        "mint_authority_active": True, "freeze_authority_active": True,
        "top10_holder_pct": 10.0, "lp_locked_pct": 100.0,
    }
    report = evaluate(market, security, "SomeMint111")
    codes = report.flag_codes()
    assert "MINT_AUTHORITY" in codes
    assert "FREEZE_AUTHORITY" in codes
    assert report.score >= 45


def test_liq_tiers_mutually_exclusive():
    market = {"liquidity_usd": 5_000, "volume_h24": 50_000,
              "market_cap": 1_000_000, "price_change_h24": 0.0}
    report = evaluate(market, {"top10_holder_pct": 10.0}, "X")
    codes = report.flag_codes()
    assert "LIQ_CRITICAL" in codes
    assert "LIQ_LOW" not in codes


def test_missing_fields_treated_as_unknown():
    # Частичные данные не должны падать и не должны давать ложных флагов
    report = evaluate({"price_usd": 1.0}, {}, "X")
    codes = report.flag_codes()
    assert "LIQ_CRITICAL" not in codes
    assert "MINT_AUTHORITY" not in codes
    assert "AUTHORITIES_REVOKED" not in codes  # None != «отозваны»


def test_ath_crash_flag():
    # Профиль PLAY: TGE-дамп, -94.6% от ATH
    market = {"liquidity_usd": 84_000, "volume_h24": 700,
              "market_cap": 528_000, "price_change_h24": -8.2,
              "ath_change_pct": -94.6}
    report = evaluate(market, {"top10_holder_pct": 95.4, "lp_locked_pct": 0.0}, "PLAYs111")
    codes = report.flag_codes()
    assert "ATH_CRASH" in codes
    assert "TOP10_EXTREME" in codes       # >90% теперь critical
    assert "TOP10_HEAVY" not in codes     # взаимоисключающие ступени
    assert report.level == "high"         # 15+12+20+15 = 62


def test_market_stale_fake_liquidity():
    # Объём < 1% ликвидности: рынок мёртв, хоть ликвидность и есть
    market = {"liquidity_usd": 500_000, "volume_h24": 2_000,
              "market_cap": 5_000_000, "price_change_h24": 0.0}
    report = evaluate(market, {"top10_holder_pct": 10.0}, "X")
    codes = report.flag_codes()
    assert "MARKET_STALE" in codes
    assert "ACTIVE_MARKET" not in codes


def test_greens_do_not_change_score():
    market = {"liquidity_usd": 5_000, "volume_h24": 50_000,
              "market_cap": 1_000_000, "price_change_h24": 0.0}
    security = {"mint_authority_active": False, "freeze_authority_active": False,
                "top10_holder_pct": 10.0, "lp_locked_pct": 100.0,
                "holders_count": 20_000}
    with_greens = evaluate(market, security, "X")
    reds_only = sum(1 for f in with_greens.flags if f.severity != "good")
    assert reds_only < len(with_greens.flags)  # зелёные есть
    # score считается только по красным: LIQ_CRITICAL(30) + LIQ_MCAP_RATIO(15) = 45
    assert with_greens.score == 45
