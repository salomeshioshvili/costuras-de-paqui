"""Pulls the latest exchange rates and stores a row per currency."""
from django.core.management.base import BaseCommand

from shop.services import fx


class Command(BaseCommand):
    help = 'Refresh exchange rates for all known currencies.'

    def handle(self, *args, **options):
        n = fx.refresh_all_rates()
        self.stdout.write(self.style.SUCCESS(f'Refreshed {n} rates.'))
