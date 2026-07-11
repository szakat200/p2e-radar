"""Форматирование отчётов для Telegram (ParseMode.HTML)."""
import html
from datetime import datetime, timezone

from analyzer.risk_engine import RiskReport

SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "info": "ℹ️", "good": "✅"}
LEVEL_LABEL = {"low": "🟢 НИЗКИЙ", "medium": "🟡 СРЕДНИЙ", "high": "🔴 ВЫСОКИЙ"}


def esc(text: str | None) -> str:
    return html.escape(str(text)) if text is not None else ""


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    if v >= 1:
        return f"${v:.2f}"
    return f"${v:.8f}".rstrip("0")


def fmt_pct(v: float | None) -> str:
    return f"{v:+.1f}%" if v is not None else "—"


def _pair_age(pair_created_at) -> str:
    if not pair_created_at:
        return "—"
    created = pair_created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - created).days
    return f"{days} дн."


def format_check_report(mint: str, market: dict | None, security: dict | None,
                        report: RiskReport) -> str:
    """Полный разбор для /check и /watch."""
    symbol = (market or {}).get("symbol") or "?"
    name = (market or {}).get("name") or ""
    lines = [
        f"<b>{esc(symbol)}</b> {esc(name)}",
        f"<code>{esc(mint)}</code>",
        "",
    ]
    if market:
        lines += [
            f"💰 Цена: <b>{fmt_usd(market.get('price_usd'))}</b> "
            f"({fmt_pct(market.get('price_change_h24'))} за 24ч)",
            f"💧 Ликвидность: <b>{fmt_usd(market.get('liquidity_usd'))}</b>",
            f"📊 Объём 24ч: {fmt_usd(market.get('volume_h24'))}",
            f"🏦 Market cap: {fmt_usd(market.get('market_cap'))}",
            f"⏳ Возраст пары: {_pair_age(market.get('pair_created_at'))} "
            f"({esc(market.get('dex_id') or '?')})",
        ]
    else:
        lines.append("💀 Торговая пара не найдена")

    if security:
        holders = security.get("holders_count")
        top10 = security.get("top10_holder_pct")
        lines.append(
            f"👥 Холдеры: {holders if holders is not None else '—'}"
            + (f", топ-10 держат {top10:.0f}%" if top10 is not None else "")
        )
    lines += [
        "",
        f"Риск: <b>{report.score}/100 — {LEVEL_LABEL[report.level]}</b>",
    ]
    reds = [f for f in report.flags if f.severity != "good"]
    greens = [f for f in report.flags if f.severity == "good"]
    if reds:
        lines.append("")
        for f in reds:
            lines.append(f"{SEVERITY_ICON[f.severity]} <b>{esc(f.title)}</b> — {esc(f.detail)}")
    else:
        lines.append("\n✅ Красных флагов не найдено")
    if greens:
        lines.append("")
        for f in greens:
            lines.append(f"✅ <b>{esc(f.title)}</b> — {esc(f.detail)}")
    return "\n".join(lines)


def format_watchlist_row(token) -> str:
    level = token.risk_level or "?"
    icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(level, "⚪")
    score = f"{token.risk_score}/100" if token.risk_score is not None else "—"
    return (
        f"{icon} <b>{esc(token.symbol or token.mint[:8])}</b> "
        f"{fmt_usd(token.price_usd)} | liq {fmt_usd(token.liquidity_usd)} | "
        f"риск {score}\n<code>{esc(token.mint)}</code>"
    )


def format_catalog_row(idx: int, token) -> str:
    return (
        f"{idx}. <b>{esc(token.symbol or '?')}</b> {esc(token.name or '')} — "
        f"mcap {fmt_usd(token.market_cap)}, 24ч {fmt_pct(token.price_change_h24)}\n"
        f"<code>{esc(token.mint)}</code>"
    )
