"""Cache for market metadata from the Gamma API."""

import time
import requests
import config

_cache: dict[str, dict] = {}
_cache_ttl = 300  # 5 minutes


def get_market(condition_id: str) -> dict | None:
    """Fetch market info by condition_id, with caching."""
    entry = _cache.get(condition_id)
    if entry and time.time() - entry["ts"] < _cache_ttl:
        return entry["data"]

    try:
        resp = requests.get(
            f"{config.GAMMA_API_URL}/markets",
            params={"condition_id": condition_id},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
        if markets:
            data = markets[0]
            _cache[condition_id] = {"data": data, "ts": time.time()}
            return data
    except Exception as e:
        print(f"[market_cache] Failed to fetch market {condition_id}: {e}")
    return None


def get_market_by_token(token_id: str) -> dict | None:
    """Fetch market info by CLOB token ID."""
    entry = _cache.get(f"token:{token_id}")
    if entry and time.time() - entry["ts"] < _cache_ttl:
        return entry["data"]

    try:
        resp = requests.get(
            f"{config.GAMMA_API_URL}/markets",
            params={"clob_token_ids": token_id},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
        if markets:
            data = markets[0]
            _cache[f"token:{token_id}"] = {"data": data, "ts": time.time()}
            _cache[data.get("conditionId", "")] = {"data": data, "ts": time.time()}
            return data
    except Exception as e:
        print(f"[market_cache] Failed to fetch market by token {token_id}: {e}")
    return None
