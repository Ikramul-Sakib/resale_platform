"""
Management command: purge_expired_scans

Deletes guest scans (and their stored images) older than
GUEST_SCAN_RETENTION_HOURS. Schedule it (e.g. hourly cron).

Usage:
    python manage.py purge_expired_scans
    python manage.py purge_expired_scans --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.scans.services import purge_expired_guest_scans


class Command(BaseCommand):
    help = "Delete guest scans and images older than GUEST_SCAN_RETENTION_HOURS."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report the count without deleting.")

    def handle(self, *args, **options):
        count = purge_expired_guest_scans(dry_run=options["dry_run"])
        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {count} guest scan(s) older than {settings.GUEST_SCAN_RETENTION_HOURS}h."
            )
        )
