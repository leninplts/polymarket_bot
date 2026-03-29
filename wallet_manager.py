"""Persistent wallet management — add/remove wallets without redeploying."""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
WALLETS_FILE = os.path.join(DATA_DIR, "wallets.json")


def _load() -> list[dict]:
    """Load wallets from disk. Each entry: {address, nickname, added_at}"""
    if not os.path.exists(WALLETS_FILE):
        return []
    try:
        with open(WALLETS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save(wallets: list[dict]):
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)


def get_all() -> list[dict]:
    return _load()


def get_addresses() -> list[str]:
    return [w["address"].lower() for w in _load()]


def get_nickname(address: str) -> str:
    """Get nickname for an address, or short address if none."""
    for w in _load():
        if w["address"].lower() == address.lower():
            return w.get("nickname") or f"{address[:10]}...{address[-6:]}"
    return f"{address[:10]}...{address[-6:]}"


def add_wallet(address: str, nickname: str = "") -> bool:
    """Add a wallet. Returns False if already exists."""
    wallets = _load()
    address = address.lower().strip()

    for w in wallets:
        if w["address"] == address:
            return False

    from datetime import datetime
    wallets.append({
        "address": address,
        "nickname": nickname or "",
        "added_at": datetime.now().isoformat(),
    })
    _save(wallets)
    return True


def remove_wallet(address: str) -> bool:
    """Remove a wallet. Returns False if not found."""
    wallets = _load()
    address = address.lower().strip()
    original_len = len(wallets)
    wallets = [w for w in wallets if w["address"] != address]

    if len(wallets) == original_len:
        return False

    _save(wallets)
    return True


def set_nickname(address: str, nickname: str) -> bool:
    """Set nickname for a wallet."""
    wallets = _load()
    address = address.lower().strip()

    for w in wallets:
        if w["address"] == address:
            w["nickname"] = nickname
            _save(wallets)
            return True
    return False


def pause_wallet(address: str) -> bool:
    """Pause copying from a wallet. Returns False if not found."""
    wallets = _load()
    address = address.lower().strip()
    for w in wallets:
        if w["address"] == address:
            if w.get("paused"):
                return False  # already paused
            w["paused"] = True
            from datetime import datetime
            w["paused_at"] = datetime.now().isoformat()
            _save(wallets)
            return True
    return False


def resume_wallet(address: str) -> bool:
    """Resume copying from a wallet. Returns False if not found or not paused."""
    wallets = _load()
    address = address.lower().strip()
    for w in wallets:
        if w["address"] == address:
            if not w.get("paused"):
                return False  # not paused
            w["paused"] = False
            w.pop("paused_at", None)
            _save(wallets)
            return True
    return False


def is_paused(address: str) -> bool:
    """Check if a wallet is manually paused."""
    for w in _load():
        if w["address"].lower() == address.lower():
            return bool(w.get("paused", False))
    return False


def get_active_addresses() -> list[str]:
    """Return only non-paused wallet addresses."""
    return [w["address"].lower() for w in _load() if not w.get("paused", False)]


def init_from_config(addresses: list[str]):
    """Initialize wallets.json from config if it doesn't exist yet."""
    if os.path.exists(WALLETS_FILE):
        return

    wallets = []
    from datetime import datetime
    for addr in addresses:
        wallets.append({
            "address": addr.lower().strip(),
            "nickname": "",
            "added_at": datetime.now().isoformat(),
        })
    _save(wallets)
