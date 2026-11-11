"""
Delete stored image files when ScanImage rows are deleted (including
cascades from Scan or User deletion), after the transaction commits.
"""

import logging

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ScanImage

logger = logging.getLogger(__name__)


def _delete_file(storage_key: str) -> None:
    try:
        default_storage.delete(storage_key)
    except Exception:
        logger.exception("scan_image.file_delete_failed")


@receiver(post_delete, sender=ScanImage)
def delete_scan_image_file(sender, instance, **kwargs):
    storage_key = instance.storage_key
    transaction.on_commit(lambda: _delete_file(storage_key), robust=True)
