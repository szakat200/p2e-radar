"""Веб-панель P2E Radar. Отдельный процесс: uvicorn web_app:app --port 8010"""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from db.database import AsyncSessionLocal, init_db
from db.models import AlertLog, Token, TokenSecurity, TokenSnapshot

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="Solana P2E Radar")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await init_db()


def _dt(v: datetime | None) -> str | None:
    return v.isoformat() + "Z" if v else None


def _token_dict(t: Token) -> dict:
    return {
        "mint": t.mint, "symbol": t.symbol, "name": t.name,
        "source": t.source, "coingecko_id": t.coingecko_id,
        "image_url": t.image_url,
        "categories": t.categories or [], "watched": t.watched,
        "links": t.links, "description": t.description,
        "price_usd": t.price_usd, "liquidity_usd": t.liquidity_usd,
        "volume_h24": t.volume_h24, "market_cap": t.market_cap,
        "price_change_h24": t.price_change_h24,
        "ath_change_pct": t.ath_change_pct,
        "pair_created_at": _dt(t.pair_created_at), "dex_id": t.dex_id,
        "risk_score": t.risk_score, "risk_level": t.risk_level,
        "risk_flags": t.risk_flags or [],
        "metrics_updated_at": _dt(t.metrics_updated_at),
        "first_seen_at": _dt(t.first_seen_at),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/stats")
async def stats() -> dict:
    async with AsyncSessionLocal() as db:
        total = (await db.execute(
            select(func.count()).select_from(Token)
            .where(Token.source == "catalog"))).scalar()
        watched = (await db.execute(
            select(func.count()).select_from(Token).where(Token.watched.is_(True)))).scalar()
        high_risk = (await db.execute(
            select(func.count()).select_from(Token)
            .where(Token.watched.is_(True), Token.risk_level == "high"))).scalar()
        day_ago = datetime.utcnow() - timedelta(hours=24)
        alerts_24h = (await db.execute(
            select(func.count()).select_from(AlertLog)
            .where(AlertLog.sent_at >= day_ago))).scalar()
        return {"catalog_total": total, "watched": watched,
                "watched_high_risk": high_risk, "alerts_24h": alerts_24h}


@app.get("/api/catalog")
async def catalog(q: str | None = None, limit: int = Query(100, ge=1, le=500)) -> list:
    async with AsyncSessionLocal() as db:
        query = select(Token).where(Token.source == "catalog")
        if q:
            like = f"%{q}%"
            query = query.where(Token.name.ilike(like) | Token.symbol.ilike(like))
        query = query.order_by(Token.market_cap.desc().nullslast()).limit(limit)
        return [_token_dict(t) for t in (await db.execute(query)).scalars().all()]


@app.get("/api/tokens")
async def tokens() -> list:
    async with AsyncSessionLocal() as db:
        query = select(Token).where(Token.watched.is_(True)) \
            .order_by(Token.risk_score.desc().nullslast())
        return [_token_dict(t) for t in (await db.execute(query)).scalars().all()]


@app.get("/api/tokens/{mint}")
async def token_detail(mint: str) -> dict:
    async with AsyncSessionLocal() as db:
        token = (await db.execute(
            select(Token).where(Token.mint == mint))).scalar_one_or_none()
        if not token:
            raise HTTPException(404, "token not found")
        sec = (await db.execute(
            select(TokenSecurity).where(TokenSecurity.token_id == token.id)
        )).scalar_one_or_none()
        week_ago = datetime.utcnow() - timedelta(days=7)
        snaps = (await db.execute(
            select(TokenSnapshot)
            .where(TokenSnapshot.token_id == token.id, TokenSnapshot.ts >= week_ago)
            .order_by(TokenSnapshot.ts))).scalars().all()
        return {
            **_token_dict(token),
            "security": {
                "mint_authority_active": sec.mint_authority_active,
                "freeze_authority_active": sec.freeze_authority_active,
                "top10_holder_pct": sec.top10_holder_pct,
                "lp_locked_pct": sec.lp_locked_pct,
                "rugcheck_score": sec.rugcheck_score,
                "holders_count": sec.holders_count,
                "source": sec.source, "checked_at": _dt(sec.checked_at),
            } if sec else None,
            "snapshots": [
                {"ts": _dt(s.ts), "price_usd": s.price_usd,
                 "liquidity_usd": s.liquidity_usd, "volume_h24": s.volume_h24}
                for s in snaps
            ],
        }


@app.get("/api/alerts")
async def alerts(limit: int = Query(50, ge=1, le=200)) -> list:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AlertLog).order_by(AlertLog.sent_at.desc()).limit(limit)
        )).scalars().all()
        return [
            {"alert_type": a.alert_type, "entity_key": a.entity_key,
             "message": a.message, "sent_at": _dt(a.sent_at)}
            for a in rows
        ]
