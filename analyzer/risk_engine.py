"""Оценка риска токена. Чистые функции — без I/O и БД, легко тестировать.

evaluate(market, security) -> RiskReport(score 0-100, level, flags).
Все пороги — константы модуля, правятся в одном месте.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Пороги ---
LIQ_CRITICAL_USD = 10_000
LIQ_LOW_USD = 50_000
LIQ_MCAP_RATIO_MIN = 0.02
VOLUME_DEAD_USD = 1_000
VOLUME_LOW_USD = 10_000
PRICE_COLLAPSE_PCT = -40.0
PRICE_DOWNTREND_PCT = -20.0
YOUNG_TOKEN_DAYS = 14
TOP10_HEAVY_PCT = 50.0
TOP10_NOTABLE_PCT = 30.0
LP_LOCKED_MIN_PCT = 50.0
MCAP_MICRO_USD = 100_000

LEVEL_MEDIUM_FROM = 30
LEVEL_HIGH_FROM = 60


@dataclass
class Flag:
    code: str
    severity: str  # critical | high | medium | info
    title: str     # короткий заголовок (RU)
    detail: str    # конкретика с числами

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "title": self.title, "detail": self.detail}


@dataclass
class RiskReport:
    score: int
    level: str  # low | medium | high
    flags: list[Flag] = field(default_factory=list)

    def flag_codes(self) -> set[str]:
        return {f.code for f in self.flags}


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def evaluate(market: dict | None, security: dict | None, mint: str = "") -> RiskReport:
    """market: {price_usd, liquidity_usd, volume_h24, market_cap, price_change_h24,
                pair_created_at: datetime|None}
    security: {mint_authority_active, freeze_authority_active, top10_holder_pct,
               lp_locked_pct} — поля могут отсутствовать/быть None.
    """
    flags: list[Flag] = []
    score = 0

    def add(code, severity, title, detail, penalty):
        nonlocal score
        flags.append(Flag(code, severity, title, detail))
        score += penalty

    # --- Рынок ---
    if not market:
        add("NO_PAIR", "critical", "Нет торговой пары",
            "DexScreener не нашёл ни одной пары — токен не торгуется", 40)
    else:
        liq = market.get("liquidity_usd")
        mcap = market.get("market_cap")
        vol = market.get("volume_h24")
        change = market.get("price_change_h24")
        pair_created = market.get("pair_created_at")

        if liq is not None:
            if liq < LIQ_CRITICAL_USD:
                add("LIQ_CRITICAL", "critical", "Критически низкая ликвидность",
                    f"Ликвидность {_fmt_usd(liq)} < {_fmt_usd(LIQ_CRITICAL_USD)} — "
                    "выйти из позиции без больших потерь невозможно", 30)
            elif liq < LIQ_LOW_USD:
                add("LIQ_LOW", "high", "Низкая ликвидность",
                    f"Ликвидность {_fmt_usd(liq)} — заметный слиппедж при входе/выходе", 15)
            if mcap and mcap > 0 and liq / mcap < LIQ_MCAP_RATIO_MIN:
                add("LIQ_MCAP_RATIO", "high", "Ликвидность не подкреплена капитализацией",
                    f"Liq/MCap = {liq / mcap:.1%} < {LIQ_MCAP_RATIO_MIN:.0%} — "
                    "капитализация «бумажная»", 15)

        if vol is not None:
            if vol < VOLUME_DEAD_USD:
                add("VOLUME_DEAD", "high", "Мёртвый объём торгов",
                    f"Объём за 24ч {_fmt_usd(vol)} — токеном почти не торгуют", 15)
            elif vol < VOLUME_LOW_USD:
                add("VOLUME_LOW", "medium", "Слабый объём торгов",
                    f"Объём за 24ч {_fmt_usd(vol)}", 7)

        if change is not None:
            if change < PRICE_COLLAPSE_PCT:
                add("PRICE_COLLAPSE", "high", "Обвал цены",
                    f"Цена за 24ч: {change:+.1f}%", 15)
            elif change < PRICE_DOWNTREND_PCT:
                add("PRICE_DOWNTREND", "medium", "Нисходящий тренд",
                    f"Цена за 24ч: {change:+.1f}%", 7)

        if pair_created is not None:
            created = pair_created
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days < YOUNG_TOKEN_DAYS:
                add("YOUNG_TOKEN", "medium", "Молодой токен",
                    f"Паре всего {age_days} дн. (порог {YOUNG_TOKEN_DAYS})", 10)

        if mcap is not None and 0 < mcap < MCAP_MICRO_USD:
            add("MCAP_MICRO", "medium", "Микро-капитализация",
                f"Market cap {_fmt_usd(mcap)} < {_fmt_usd(MCAP_MICRO_USD)}", 8)

    # --- On-chain ---
    if not security:
        add("NO_ONCHAIN_DATA", "info", "Нет on-chain данных",
            "RugCheck и RPC недоступны — authority и холдеры не проверены", 5)
    else:
        if security.get("mint_authority_active"):
            add("MINT_AUTHORITY", "critical", "Mint authority активен",
                "Создатель может напечатать новые токены и размыть твою долю", 25)
        if security.get("freeze_authority_active"):
            add("FREEZE_AUTHORITY", "critical", "Freeze authority активен",
                "Создатель может заморозить твои токены — продать не сможешь", 20)

        top10 = security.get("top10_holder_pct")
        if top10 is not None:
            if top10 > TOP10_HEAVY_PCT:
                add("TOP10_HEAVY", "high", "Концентрация у китов",
                    f"Топ-10 держат {top10:.0f}% supply — один слив обвалит цену", 15)
            elif top10 > TOP10_NOTABLE_PCT:
                add("TOP10_NOTABLE", "medium", "Заметная концентрация",
                    f"Топ-10 держат {top10:.0f}% supply", 8)

        lp = security.get("lp_locked_pct")
        if lp is not None and lp < LP_LOCKED_MIN_PCT:
            add("LP_UNLOCKED", "high", "LP не заблокирован",
                f"Заблокировано/сожжено {lp:.0f}% LP — возможен rug pull", 15)

    # --- Прочее ---
    if mint.lower().endswith("pump"):
        add("PUMPFUN_ORIGIN", "info", "Происхождение pump.fun",
            "Токен создан через pump.fun — типичная площадка мемкоинов", 5)

    score = min(score, 100)
    level = "high" if score >= LEVEL_HIGH_FROM else (
        "medium" if score >= LEVEL_MEDIUM_FROM else "low")
    return RiskReport(score=score, level=level, flags=flags)
