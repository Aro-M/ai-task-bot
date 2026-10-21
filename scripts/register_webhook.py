"""Operator-invoked registration; never print the token or token-bearing URL."""

import argparse
import asyncio
from urllib.parse import urlparse

from aiogram import Bot

from app.config import settings


async def register(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path != "/telegram/webhook"
    ):
        raise SystemExit("Provide an HTTPS URL ending in /telegram/webhook")
    if not settings.telegram_bot_token or not settings.webhook_secret:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and WEBHOOK_SECRET in .env first")
    try:
        async with Bot(settings.telegram_bot_token) as bot:
            await bot.set_webhook(
                url,
                secret_token=settings.webhook_secret,
                allowed_updates=["message"],
                drop_pending_updates=False,
            )
    except Exception:
        raise SystemExit(
            "Webhook registration failed; verify credentials and connectivity"
        ) from None
    print("Webhook registered. Pending updates were preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    asyncio.run(register(parser.parse_args().url))
