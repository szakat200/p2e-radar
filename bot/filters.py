from aiogram.filters import BaseFilter
from aiogram.types import Message

from config import config


class AdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user) and message.from_user.id in config.ADMIN_IDS
