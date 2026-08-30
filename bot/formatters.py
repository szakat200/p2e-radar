"""Форматирование отчётов для Telegram (ParseMode.HTML)."""
import html
from datetime import date, datetime, timezone

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


STAGE_LABEL = {
    "mainnet": "mainnet", "beta": "бета", "alpha": "альфа", "open_alpha": "откр. альфа",
    "devnet": "devnet", "pre-launch": "до запуска", "pre_launch": "до запуска",
    "prelaunch": "до запуска", "early-access": "ранний доступ", "live": "live",
    "launched": "запущена", "token-live": "токен live", "preview": "превью",
    "dead": "мертва",
}


def days_since(launch_date: str | None) -> int | None:
    """Дней с даты запуска (YYYY-MM-DD)."""
    if not launch_date:
        return None
    try:
        return (date.today() - date.fromisoformat(str(launch_date)[:10])).days
    except ValueError:
        return None


def fmt_launch(launch_date: str | None) -> str:
    days = days_since(launch_date)
    if days is None:
        return "дата запуска неизвестна"
    if days == 0:
        return f"{launch_date} (сегодня)"
    return f"{launch_date} ({days} дн. назад)"


def format_game(game, with_desc: bool = True) -> str:
    """Карточка игры для алерта и /game."""
    stage = STAGE_LABEL.get(game.launch_stage or "", game.launch_stage or "")
    head = " · ".join(x for x in (game.genre, stage, game.launch_access) if x)
    lines = [
        f"🎮 <b>{esc(game.name)}</b>",
        esc(head) if head else "",
        f"📅 Запуск: {esc(fmt_launch(game.launch_date))}",
    ]
    if game.token_tradeable:
        ticker = f"${esc(game.token_symbol)}" if game.token_symbol else "Токен"
        lines += [
            f"💰 {ticker}: {fmt_usd(game.price_usd)} "
            f"({fmt_pct(game.price_change_h24)} за 24ч)",
            f"📊 MCap {fmt_usd(game.market_cap)} | ликв. {fmt_usd(game.liquidity_usd)} "
            f"| объём {fmt_usd(game.volume_h24)}",
        ]
        if game.ath_market_cap and game.market_cap:
            drop = (game.market_cap / game.ath_market_cap - 1) * 100
            lines.append(f"📉 От ATH-капы: {fmt_pct(drop)} (пик {fmt_usd(game.ath_market_cap)})")
    elif game.token_mint:
        lines.append("💰 Токен есть, но пара ещё не торгуется")
    else:
        lines.append("💰 Токена нет — вход только игрой (кандидат на аирдроп)")

    if game.live_online is not None:
        lines.append(f"👥 Онлайн сейчас: {game.live_online}")
    if game.risk_score is not None:
        lines.append(f"⚠️ Риск токена: <b>{game.risk_score}/100 — "
                     f"{LEVEL_LABEL.get(game.risk_level, '?')}</b>")
        reds = [f for f in (game.risk_flags or []) if f["severity"] in ("critical", "high")]
        if reds:
            lines.append("🚩 " + esc(", ".join(f["title"] for f in reds[:4])))
    if with_desc and game.tagline:
        lines += ["", f"<i>{esc(game.tagline)}</i>"]

    links = [f'<a href="{esc(game.url)}">сайт</a>' if game.url else "",
             f'<a href="{esc(game.twitter)}">X</a>' if game.twitter else "",
             f'<a href="{esc(game.solgames_url)}">solgames</a>' if game.solgames_url else ""]
    links = [x for x in links if x]
    if links:
        lines += ["", "🔗 " + " · ".join(links)]
    if game.token_mint:
        lines += [f"<code>{esc(game.token_mint)}</code>"]
    return "\n".join(x for x in lines if x != "")


def format_game_row(idx: int, game) -> str:
    """Строка в списке /games."""
    risk = (f"риск {game.risk_score}/100" if game.risk_score is not None
            else ("токена нет" if not game.token_mint else "риск —"))
    days = days_since(game.launch_date)
    age = f"{days} дн." if days is not None else "—"
    money = (f"mcap {fmt_usd(game.market_cap)}, {fmt_pct(game.price_change_h24)}"
             if game.token_tradeable else "без токена")
    return (
        f"{idx}. <b>{esc(game.name)}</b> · {esc(game.genre or '—')} · {age}\n"
        f"   {money} · {risk}"
        + (f" · 👥{game.live_online}" if game.live_online else "")
        + (f"\n   <a href=\"{esc(game.solgames_url)}\">подробнее</a>"
           if game.solgames_url else "")
    )


def format_catalog_row(idx: int, token) -> str:
    return (
        f"{idx}. <b>{esc(token.symbol or '?')}</b> {esc(token.name or '')} — "
        f"mcap {fmt_usd(token.market_cap)}, 24ч {fmt_pct(token.price_change_h24)}\n"
        f"<code>{esc(token.mint)}</code>"
    )
