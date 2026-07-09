"""Конфигурация Solana P2E Radar. Паттерн: единый Config-класс + module-global config."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    ]

    # База данных (абсолютный путь — чтобы бот и веб видели один файл)
    _DEFAULT_DB = f"sqlite+aiosqlite:///{(BASE_DIR / 'radar.db').as_posix()}"
    DATABASE_URL: str = os.getenv("DATABASE_URL", _DEFAULT_DB)

    # Внешние API
    DEXSCREENER_BASE: str = os.getenv("DEXSCREENER_BASE", "https://api.dexscreener.com")
    RUGCHECK_BASE: str = os.getenv("RUGCHECK_BASE", "https://api.rugcheck.xyz")
    COINGECKO_BASE: str = os.getenv("COINGECKO_BASE", "https://api.coingecko.com")
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")

    @property
    def SOLANA_RPC_URL(self) -> str:
        if self.HELIUS_API_KEY:
            return f"https://mainnet.helius-rpc.com/?api-key={self.HELIUS_API_KEY}"
        return "https://api.mainnet-beta.solana.com"

    @property
    def ADMIN_ID(self) -> int | None:
        return self.ADMIN_IDS[0] if self.ADMIN_IDS else None

    # Интервалы задач
    CATALOG_SYNC_HOURS: int = int(os.getenv("CATALOG_SYNC_HOURS", "6"))
    MARKET_SYNC_MINUTES: int = int(os.getenv("MARKET_SYNC_MINUTES", "5"))
    ONCHAIN_SYNC_HOURS: int = int(os.getenv("ONCHAIN_SYNC_HOURS", "6"))

    # Пороги алертов
    ALERT_LIQ_DROP_PCT: float = float(os.getenv("ALERT_LIQ_DROP_PCT", "0.30"))
    ALERT_PRICE_DROP_PCT: float = float(os.getenv("ALERT_PRICE_DROP_PCT", "0.40"))

    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()
