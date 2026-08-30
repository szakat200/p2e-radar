# 探 Solana P2E Radar

Радар игр на Solana: каталог реальных играбельных проектов, свежие запуски,
рыночные метрики их токенов, on-chain безопасность, red flags, Telegram-алерты
и веб-дашборд.

Живой дашборд: **https://szakat200.github.io/p2e-radar/** (пересобирается раз в час).

## Что умеет

- **Каталог игр** — из [solgames.buzz](https://solgames.buzz) (их JSON API): только
  Solana-native проекты с подтверждённым играбельным клиентом, датой запуска, жанром,
  онлайном игроков и резолвнутым токеном. Синк раз в час.
- **Свежие запуски** — главный сигнал радара: игра, запущенная днями назад,
  прилетает алертом в Telegram с разбором риска её токена.
- **Risk engine** — оценка 0–100 + именованные флаги (LIQ_CRITICAL, MINT_AUTHORITY,
  TOP10_HEAVY, ATH_CRASH…). Рынок берётся из каталога, on-chain (mint/freeze authority,
  топ-холдеры, LP lock) — RugCheck → Solana RPC фоллбек.
- **Каталог токенов** — P2E/gaming токены Solana из CoinGecko: мосты и зрелые проекты,
  которых нет в каталоге игр. Синк раз в 6ч.
- **Проверка любого токена**: `/check <mint>` — ликвидность, объём, mcap, возраст пары.
- **Вотчлист**: `/watch <mint>` — мониторинг каждые 5 минут.
- **Алерты в Telegram**: новая игра в каталоге, падение ликвидности >30%, цены >40%,
  новые красные флаги. Дедуп — каждый алерт приходит один раз.
- **Веб-дашборд**: игры с фильтрами и поиском, обзор, токены, вотчлист, алерты.

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
Внешних ключей радар не требует: solgames, DexScreener, CoinGecko и RugCheck
работают без авторизации.

## Команды бота

| Команда | Что делает |
|---|---|
| `/games` | Свежие запуски за 30 дней |
| `/games top` | Топ игр по капитализации |
| `/games online` | Игры с живым онлайном |
| `/games safe` | Наименее рискованные |
| `/games notoken` | Игры без токена — ранний вход |
| `/game <название>` | Карточка игры: метрики, риск, ссылки |
| `/check <mint>` | Разбор рисков токена |
| `/watch <mint>` | Добавить в вотчлист |
| `/unwatch <mint>` | Убрать из вотчлиста |
| `/watchlist` | Список с риск-бейджами |

## Архитектура

```
collectors/   solgames (каталог игр) · coingecko (токены) · dexscreener (рынок)
              onchain (RugCheck→RPC)
analyzer/     risk_engine — чистые функции, пороги-константы, tests/
bot/          aiogram 3.7, admin-only, HTML parse mode · alerts с дедупом
scheduler/    игры 1ч · токены 6ч · рынок 5мин · on-chain 6ч
web_app.py    FastAPI (отдельный процесс), общая SQLite radar.db
web/          index.html — один файл, vanilla JS, тема Neon Cyber
scripts/      export_static.py — сборка статики для GitHub Pages (без БД)
```

Дашборд на Pages собирается из тех же коллекторов, но без БД: воркфлоу
`.github/workflows/pages.yml` гоняет `scripts/export_static.py` раз в час
и кладёт `_site/` в Pages.

Тесты: `python -m pytest tests/`

## Известные грабли

- `solgames.buzz` отдаёт HTML за Cloudflare JS-challenge, а `/api/*` — открыт.
  Читаем API напрямую, Playwright не нужен.
- На ответах solgames больше ~35 КБ **aiohttp 3.9 виснет** посреди чанкед-стрима,
  поэтому этот коллектор ходит через `httpx`.
- `token_status` в solgames ненадёжен: у половины реально торгуемых пар стоит
  `"none"`. «Торгуется» определяем по наличию mint + рыночных данных.
- CoinGecko-категория `gaming` грязная (мемкоины, DePIN, мосты вроде ApeCoin
  с $20K ликвидности) — она осталась отдельной вкладкой «Токены», а не каталогом игр.
