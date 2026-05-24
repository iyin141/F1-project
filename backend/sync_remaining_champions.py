#!/usr/bin/env python
"""Sync remaining F1 champions from 2010-2026."""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.path.dirname(__file__))

django.setup()

from api.drivers.services.champions_sync_service import ChampionsSyncService
from api.models import F1Champion
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    service = ChampionsSyncService()
    
    # Get already synced years
    synced_years = set(F1Champion.objects.values_list('year', flat=True))
    logger.info(f"Already synced: {len(synced_years)} years (1950-2009)")
    
    # Sync remaining years
    missing_years = [y for y in range(2010, 2027) if y not in synced_years]
    logger.info(f"Syncing {len(missing_years)} missing years: {missing_years}")
    
    synced, errors = 0, 0
    for year in missing_years:
        result = service.sync_year_champion(year)
        if result.get('synced'):
            synced += 1
            logger.info(f"  ✓ {year}: {result.get('driver_id', 'N/A')}")
        else:
            errors += 1
            logger.info(f"  ✗ {year}: {result.get('error', 'No data')}")
    
    logger.info(f"\n✓ Synced: {synced} | Errors: {errors}")
    
    # Final count
    total = F1Champion.objects.count()
    logger.info(f"Total champions in DB: {total}")
