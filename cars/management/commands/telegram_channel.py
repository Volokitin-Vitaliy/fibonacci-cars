from django.conf import settings
from django.core.management.base import BaseCommand

from cars import channel
from cars.telegram import api


class Command(BaseCommand):
    """Posts about new cars in the Telegram channel (cars/channel.py).

    --check   checks that the bot can post in TELEGRAM_CHANNEL;
    --start   first launch: posts the 3 newest cars now, the others already on the site
              are not posted; afterwards new cars go out one an hour;
    (none)    one regular pass (run_scheduler does this every few minutes)."""

    help = 'Post new cars in the Telegram channel.'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--start', action='store_true')
        parser.add_argument('--test-count', type=int, default=3)

    def handle(self, *args, **options):
        if not channel.enabled():
            self.stdout.write('Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL in .env first.')
            return
        if options['check']:
            chat = api('getChat', chat_id=settings.TELEGRAM_CHANNEL)
            me = api('getMe')
            member = api('getChatMember', chat_id=settings.TELEGRAM_CHANNEL, user_id=me['id']) if me and chat else None
            if not chat:
                self.stdout.write(self.style.ERROR(f'Channel {settings.TELEGRAM_CHANNEL} not found (check the name).'))
            elif not member or member.get('status') != 'administrator' or not member.get('can_post_messages', True):
                self.stdout.write(self.style.ERROR(f'The bot is not an admin with "Post messages" in {chat.get("title")}.'))
            else:
                self.stdout.write(self.style.SUCCESS(f'OK: the bot can post in "{chat.get("title")}".'))
            return
        if options['start']:
            skipped, results = channel.start(options['test_count'])
            for car, ok, error in results:
                self.stdout.write(f'{"posted" if ok else "FAILED"}: {car}' + (f' ({error})' if error else ''))
            self.stdout.write(f'{skipped} cars already on the site will not be posted. New ones go out one an hour.')
            return
        self.stdout.write(channel.run())
