from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from cars import telegram


class Command(BaseCommand):
    help = 'Connect the Telegram moderation bot to the site (run once after setting the token).'

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError('Set TELEGRAM_BOT_TOKEN in .env first.')
        url = settings.SITE_URL + reverse('telegram_webhook')
        if not url.startswith('https://'):
            raise CommandError(f'Telegram needs an https address, got {url}. Check SITE_URL.')
        ok = telegram.api('setWebhook', url=url, secret_token=telegram.webhook_secret(),
                          allowed_updates=['message', 'callback_query'], drop_pending_updates=True)
        if ok is None:
            raise CommandError('Telegram refused the webhook: check the token.')
        telegram.api('setMyCommands', commands=[{'command': 'id', 'description': 'Показать мой chat id'}])
        me = telegram.api('getMe') or {}
        self.stdout.write(self.style.SUCCESS(f'Bot @{me.get("username", "?")} is connected to {url}'))
        if not settings.TELEGRAM_MODERATOR_CHAT_IDS:
            self.stdout.write('Now send /start to the bot, put the chat id it shows into '
                              'TELEGRAM_MODERATOR_CHAT_IDS in .env and restart the site.')
