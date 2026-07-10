import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.handlers import commands, group, private
from shared.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_PORT = 8080  # за nginx (Фаза 8, прод docker-compose), наружу не публикуется напрямую


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # Порядок важен: команды и приватный контент-роутер должны идти раньше
    # группового — иначе к моменту, когда апдейт дойдёт до group-роутера,
    # приватные сообщения уже будут обработаны (фильтры на chat.type это и
    # так гарантируют, но порядок регистрации оставляем явным).
    dp.include_router(commands.router)
    dp.include_router(private.router)
    dp.include_router(group.router)
    return dp


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def run_polling() -> None:
    settings = get_settings()
    bot = create_bot(settings.bot_token)
    dp = create_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    logger.info("Бот запущен: @%s (id=%s), RUN_MODE=polling", me.username, me.id)
    await dp.start_polling(bot)


async def run_webhook() -> None:
    """RUN_MODE=webhook — для прода за nginx (см. docker-compose.prod.yml,
    nginx/nginx.conf). Требует реальный публичный DASHBOARD_URL с HTTPS —
    Telegram не примет webhook на http:// или self-signed сертификат."""
    settings = get_settings()
    bot = create_bot(settings.bot_token)
    dp = create_dispatcher()

    webhook_url = f"{settings.dashboard_url.rstrip('/')}{WEBHOOK_PATH}"
    secret = settings.telegram_webhook_secret or None
    await bot.set_webhook(webhook_url, secret_token=secret, drop_pending_updates=True)
    me = await bot.get_me()
    logger.info(
        "Бот запущен: @%s (id=%s), RUN_MODE=webhook, url=%s", me.username, me.id, webhook_url
    )

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=WEBHOOK_PATH
    )
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)
    await site.start()
    logger.info("Webhook слушает на :%s%s", WEBHOOK_PORT, WEBHOOK_PATH)

    await asyncio.Event().wait()  # держим процесс живым до остановки контейнера


def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    if settings.run_mode == "webhook":
        asyncio.run(run_webhook())
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
