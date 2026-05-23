"""
Pagination Service Layer - Handles paginated results caching

Manages:
- Paginated dataset slicing (laps, positions, telemetry)
- Pagination metadata (page, page_size, total_count, total_pages)
- Cache storage with TTL per data type
- Metadata-to-data association

Pagination pattern:
  1. Full result set retrieved from data source (FastF1, database)
  2. Sliced into pages of configurable size (default: 50 items per page)
  3. Each page cached with metadata in separate keys
  4. Client requests page N → retrieve page_{N} key + metadata key

Cache key structure:
  - Pagination data: f1:{year}:{round}:{session}:{data_type}:page_{page_number}
  - Pagination metadata: f1:{year}:{round}:{session}:{data_type}:meta

TTL Strategy:
- In-progress session: 120s (live data, refresh frequently)
- Completed session: 43,200s (12 hrs, stable data)
- Historical (>1yr): 604,800s (7 days, archive)
"""

from django.core.cache import caches
from typing import Any, Optional, Dict, List
from datetime import datetime


def build_pagination_key(year: int, round_number: int, session: str, data_type: str, page: int) -> str:
    """
    Build cache key for paginated data.
    
    Args:
        year: F1 season year
        round_number: Round number
        session: Session type (e.g., "R", "Q", "P1")
        data_type: Data type (e.g., "laps", "positions", "telemetry")
        page: Page number (1-indexed)
    
    Returns:
        Cache key: f1:{year}:{round}:{session}:{data_type}:page_{page}
    """
    return f"f1:{year}:{round_number}:{session}:{data_type}:page_{page}"


def build_pagination_meta_key(year: int, round_number: int, session: str, data_type: str) -> str:
    """
    Build cache key for pagination metadata.
    
    Args:
        year: F1 season year
        round_number: Round number
        session: Session type
        data_type: Data type
    
    Returns:
        Cache key: f1:{year}:{round}:{session}:{data_type}:meta
    """
    return f"f1:{year}:{round_number}:{session}:{data_type}:meta"


def get_pagination_meta(year: int, round_number: int, session: str, data_type: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve pagination metadata.
    
    Returns dict with keys:
      - total_count: Total number of items
      - page_size: Items per page
      - total_pages: Number of pages
      - data_type: Type of data (laps, positions, telemetry)
    
    Returns None if metadata not found or expired.
    """
    cache = caches["default"]
    meta_key = build_pagination_meta_key(year, round_number, session, data_type)
    return cache.get(meta_key)


def get_page(year: int, round_number: int, session: str, data_type: str, page: int) -> Optional[List[Any]]:
    """
    Retrieve a single page of paginated data.
    
    Args:
        page: Page number (1-indexed)
    
    Returns:
        List of items for the page, or None if not found/expired
    """
    cache = caches["default"]
    page_key = build_pagination_key(year, round_number, session, data_type, page)
    return cache.get(page_key)


def set_paginated_data(
    year: int,
    round_number: int,
    session: str,
    data_type: str,
    full_data: List[Any],
    page_size: int = 50,
    ttl: int = 120,
) -> Dict[str, Any]:
    """
    Store full dataset as paginated pages in cache.
    
    Splits data into pages of page_size items, stores each page separately,
    and stores metadata.
    
    Args:
        full_data: Complete list of items to paginate
        page_size: Items per page (default: 50)
        ttl: Time-to-live in seconds
    
    Returns:
        Pagination metadata dict with keys:
          - total_count: Total items
          - page_size: Items per page
          - total_pages: Number of pages
          - data_type: Data type
    """
    cache = caches["default"]
    total_count = len(full_data)
    total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
    
    # Store each page
    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * page_size
        end_idx = min(start_idx + page_size, total_count)
        page_data = full_data[start_idx:end_idx]
        
        page_key = build_pagination_key(year, round_number, session, data_type, page_num)
        cache.set(page_key, page_data, ttl)
    
    # Store metadata
    meta = {
        "total_count": total_count,
        "page_size": page_size,
        "total_pages": total_pages,
        "data_type": data_type,
    }
    meta_key = build_pagination_meta_key(year, round_number, session, data_type)
    cache.set(meta_key, meta, ttl)
    
    return meta


def clear_pagination_data(year: int, round_number: int, session: str, data_type: str) -> None:
    """
    Clear all pages and metadata for a paginated dataset.
    
    Useful when refreshing or invalidating stale data.
    """
    cache = caches["default"]
    
    # Clear metadata first to know how many pages to delete
    meta_key = build_pagination_meta_key(year, round_number, session, data_type)
    meta = cache.get(meta_key)
    
    if meta:
        total_pages = meta.get("total_pages", 0)
        for page_num in range(1, total_pages + 1):
            page_key = build_pagination_key(year, round_number, session, data_type, page_num)
            cache.delete(page_key)
    
    cache.delete(meta_key)
