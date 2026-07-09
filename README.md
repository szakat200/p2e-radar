# 探 Solana P2E Radar

Сканер play-to-earn игр и токенов на Solana: рыночные метрики, on-chain безопасность,
red flags, Telegram-алерты и веб-дашборд (Edo Noir).

## Что умеет

- **Каталог**: P2E/gaming токены на Solana из CoinGecko (с mint-адресами), синк каждые 6ч
- **Проверка токена**: `/check <mint>` — ликвидность, объём, mcap, возраст пары (DexScreener)
  + mint/freeze authority, топ-холдеры, LP lock (RugCheck → Solana RPC фоллбек)
- **Risk engine**: оценка 0–100 + именованные флаги (LIQ_CRITICAL, MINT_AUTHORITY, TOP10_HEAVY…)
- **Вотчлист**: `/watch <mint>` — мониторинг каждые 5 минут
- **Алерты в Telegram**: падение ликвидности >30%, цены >40%, новые красные флаги,
  новые игры в каталоге. Дедуп — каждый алерт приходит один раз.
- **Веб-дашборд**: обзор, каталог с поиском, вотчлист с деталями, история алертов

## Запуск

```bash
pip install -r requirements.txt
copy .env.example .env   # заполнить BOT_TOKEN и ADMIN_IDS

# Процесс 1: бот + сборщики
python main.py

# Процесс 2: веб-панель -> http://localhost:8010
python -m uvicorn web_app:app --port 8010
```

`HELIUS_API_KEY` в .env опционален — без него используется публичный Solana RPC.

## Команды бота

| Команда | Что делает |
|---|---|
| `/check <mint>` | Разбор рисков токена |
| `/watch <mint>` | Добавить в вотчлист |
| `/unwatch <mint>` | Убрать из вотчлиста |
| `/watchlist` | Список с риск-бейджами |
| `/games` | Топ P2E-игр по market cap |
| `/games new` | Новые в каталоге за 7 дней |

## Архитектура

```
collectors/   coingecko (каталог) · dexscreener (рынок) · onchain (RugCheck→RPC)
analyzer/     risk_engine — чистые функции, пороги-константы, tests/
bot/          aiogram 3.7, admin-only, HTML parse mode · alerts с дедупом
scheduler/    APScheduler: каталог 6ч · рынок 5мин · on-chain 6ч
web_app.py    FastAPI (отдельный процесс), общая SQLite radar.db
web/          index.html — один файл, vanilla JS, тема Edo Noir
```

Тесты: `python -m pytest tests/`
