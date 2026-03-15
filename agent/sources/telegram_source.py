import logging
import os
from datetime import datetime
from typing import Optional, Set

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

from event_queue import Event, get_queue

logger = logging.getLogger("TelegramSource")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_IDS = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")


class TelegramSource:
    """
    Telegram Bot source.  Converts incoming Telegram messages into Events
    and pushes them onto the shared queue.  The reply_fn callback sends
    the agent result back to the originating chat.
    """

    def __init__(self, token: str = TELEGRAM_BOT_TOKEN):
        if not token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN environment variable is not set. "
                "Create a bot via @BotFather and set the token."
            )
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self._allowed_ids: Set[int] = set()

        if TELEGRAM_ALLOWED_CHAT_IDS:
            self._allowed_ids = {
                int(x.strip())
                for x in TELEGRAM_ALLOWED_CHAT_IDS.split(",")
                if x.strip().lstrip("-").isdigit()
            }
            logger.info(f"TelegramSource: allowed chat IDs = {self._allowed_ids}")
        else:
            logger.warning(
                "TELEGRAM_ALLOWED_CHAT_IDS not set — all chats accepted. "
                "Set this to restrict access to your bot."
            )

        self._register_handlers()

    def _is_allowed(self, chat_id: int) -> bool:
        return not self._allowed_ids or chat_id in self._allowed_ids

    def _register_handlers(self):
        @self.dp.message(CommandStart())
        async def start_handler(message: types.Message):
            await message.answer(
                "Hola! Soy Open-Claudio, tu asistente de automatización del hogar.\n"
                "Puedes pedirme que controle las persianas, la puerta, o cualquier otra tarea."
            )

        @self.dp.message()
        async def message_handler(message: types.Message):
            if not message.text:
                return

            chat_id = message.chat.id
            if not self._is_allowed(chat_id):
                logger.warning(f"Rejected message from unauthorized chat_id: {chat_id}")
                await message.answer("No autorizado.")
                return

            queue = get_queue()
            username = message.from_user.username if message.from_user else "unknown"

            async def reply_fn(result: str):
                await message.answer(result)

            event = Event(
                source="telegram",
                event_type="message",
                topic="telegram/chat",
                payload={"text": message.text},
                timestamp=datetime.now(),
                metadata={
                    "chat_id": chat_id,
                    "username": username,
                    "message_id": message.message_id,
                },
                reply_fn=reply_fn,
            )

            logger.info(f"Telegram <- @{username} (chat={chat_id}): '{message.text[:80]}'")
            await queue.put(event)

    async def run(self):
        logger.info("TelegramSource starting polling...")
        await self.dp.start_polling(self.bot)

    async def stop(self):
        await self.dp.stop_polling()
        await self.bot.session.close()
