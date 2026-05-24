#!/usr/bin/env python
"""Quick script to sync champions into F1Champion table."""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.path.dirname(__file__))

django.setup()

from api.drivers.services.champions_sync_service import ChampionsSyncService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    service = ChampionsSyncService()
    logger.info("Starting champion sync (1950-2026)...")
    result = service.sync_all_champions()
    logger.info(f"Sync complete: {result}")
    
    # Verify count
    from api.models import F1Champion
    count = F1Champion.objects.count()
    logger.info(f"Total champions in DB: {count}")
