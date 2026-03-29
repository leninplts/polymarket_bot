"""
Polymarket Wallet Scanner

Source: Polymarket official leaderboard (scraped via requests)
Filters applied on top of leaderboard data:
- Active in last 7 days
- Account age > 30 days (skipped if API returns no data)

Can run standalone or be called by the bot for auto-scanning.
"""

import time
import argparse
import requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import re

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API  = "https://data-api.polymarket.com"
LEADERBOARD_URL = "https://polymarket.com/leaderboard"

# Post-scan filters (leaderboard already ranks by PnL so no PnL/WR/ROI filter needed)
MAX_INACTIVE_DAYS   = 7
MIN_ACCOUNT_AGE_DAYS = 30   # Skipped if API returns 0 (data unavailable)

# Parallelism
WALLET_WORKERS = 20

# Keep legacy constants so telegram_commands.py imports don't break
MIN_PNL       = 0
MIN_WIN_RATE  = 0.0
MIN_ROI       = 0.0
MIN_POSITIONS = 0
MARKET_WORKERS = 10

# Thread-safe print lock
_print_lock = threading.Lock()

def _tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


# ── Legacy helpers kept for backward-compat ──────────────────────────────────

def get_top_markets(limit: int = 50) -> list[dict]:
    """Fetch the most active markets (kept for backward compatibility)."""
    resp = requests.get(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "order": "volume", "ascending": "false", "active": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_market_traders(market: dict, quiet: bool = False) -> set:
    """Scrape trader addresses from a single market (kept for backward compat)."""
    condition_id = market.get("conditionId", "")
    slug = market.get("slug", "")
    question = market.get("question", slug)[:60]
    addresses = set()
    try:
        for offset in range(0, 500, 100):
            resp = requests.get(
                f"{DATA_API}/trades",
                params={"market": condition_id, "limit": 100, "offset": offset},
                timeout=15,
            )
            resp.raise_for_status()
            trades = resp.json()
            if not trades:
                break
            for trade in trades:
                addr = trade.get("proxyWallet")
                if addr:
                    addresses.add(addr.lower())
        if not quiet:
            _tprint(f"  OK {question} ({len(addresses)} traders)")
    except Exception as e:
        if not quiet:
            _tprint(f"  ERR {question}: {e}")
    return addresses


# ── New leaderboard scraper ───────────────────────────────────────────────────

def get_leaderboard_wallets(period: str = "all") -> list[dict]:
    """
    Scrape Polymarket leaderboard and return list of
    {"address": "0x...", "nickname": "...", "leaderboard_pnl": float, "rank": int}

    period: "today" | "weekly" | "monthly" | "all"
    """
    period_param = {"today": "day", "weekly": "week", "monthly": "month", "all": "all"}.get(period, "all")
    url = f"{LEADERBOARD_URL}?period={period_param}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        raise RuntimeError(f"Failed to fetch leaderboard: {e}")

    # Extract wallet addresses from href="/profile/0x..."
    addresses = re.findall(r'href="/profile/(0x[a-fA-F0-9]{40})"', html)
    # Deduplicate preserving order
    seen = set()
    unique_addresses = []
    for addr in addresses:
        a = addr.lower()
        if a not in seen:
            seen.add(a)
            unique_addresses.append(a)

    # Extract names — they appear as text nodes near the profile links
    # Pattern: the name appears right after the profile link in the HTML
    name_pattern = re.findall(
        r'href="/profile/0x[a-fA-F0-9]{40}"[^>]*>([^<]{1,40})</a>',
        html
    )

    # Extract PnL values — format: +$1,234,567 or -$1,234
    pnl_pattern = re.findall(r'([+-])\$([0-9,]+)', html)
    pnl_values = []
    for sign, val in pnl_pattern:
        try:
            pnl_values.append(float(sign + val.replace(",", "")))
        except Exception:
            pass

    results = []
    for i, addr in enumerate(unique_addresses):
        nickname = name_pattern[i] if i < len(name_pattern) else ""
        nickname = nickname.strip()
        lb_pnl = pnl_values[i] if i < len(pnl_values) else 0.0
        results.append({
            "address": addr,
            "nickname": nickname,
            "leaderboard_pnl": lb_pnl,
            "rank": i + 1,
        })

    return results


# ── Profile / activity helpers ────────────────────────────────────────────────

def _get_profile(address: str) -> dict:
    """Fetch nickname and first trade timestamp from activity history."""
    nickname = ""
    first_trade_ts = 0
    total_historical_trades = 0

    try:
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            nickname = data[0].get("name") or data[0].get("pseudonym") or ""
    except Exception:
        pass

    try:
        for check_offset in [500, 200, 50]:
            resp = requests.get(
                f"{DATA_API}/activity",
                params={"user": address, "limit": 1, "offset": check_offset},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                total_historical_trades = check_offset + 1
                first_trade_ts = float(data[0].get("timestamp", 0))
            else:
                break

        if total_historical_trades > 500:
            for check_offset in [2000, 1000, 750]:
                try:
                    resp = requests.get(
                        f"{DATA_API}/activity",
                        params={"user": address, "limit": 1, "offset": check_offset},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data:
                        total_historical_trades = check_offset + 1
                        first_trade_ts = float(data[0].get("timestamp", 0))
                    else:
                        break
                except Exception:
                    break
    except Exception:
        pass

    return {
        "nickname": nickname,
        "first_trade_ts": first_trade_ts,
        "total_historical_trades": total_historical_trades,
    }


def scan_wallet(address: str, leaderboard_data: dict = None) -> dict:
    """
    Analyze a wallet.
    If leaderboard_data is provided (address, nickname, leaderboard_pnl, rank),
    we use that PnL directly and skip the /positions scan.
    We still fetch activity for last-trade timestamp and account age.
    """
    lb = leaderboard_data or {}
    nickname = lb.get("nickname", "")
    leaderboard_pnl = lb.get("leaderboard_pnl", 0.0)
    rank = lb.get("rank", 0)

    # Get last trade time + account age from activity
    last_trade_ts = 0
    first_trade_ts = 0
    total_historical_trades = 0

    try:
        # Most recent trade
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            last_trade_ts = float(data[0].get("timestamp", 0))
            if not nickname:
                nickname = data[0].get("name") or data[0].get("pseudonym") or ""
    except Exception:
        pass

    # Account age: try a few offsets
    try:
        for check_offset in [200, 50]:
            resp = requests.get(
                f"{DATA_API}/activity",
                params={"user": address, "limit": 1, "offset": check_offset},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                total_historical_trades = check_offset + 1
                first_trade_ts = float(data[0].get("timestamp", 0))
            else:
                break
    except Exception:
        pass

    days_since = (time.time() - last_trade_ts) / 86400 if last_trade_ts > 0 else 999
    account_age_days = round((time.time() - first_trade_ts) / 86400) if first_trade_ts > 0 else 0

    # Get current open positions for category breakdown
    categories = Counter()
    open_positions = 0
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": address},
            timeout=15,
        )
        resp.raise_for_status()
        positions = resp.json()
        for pos in positions:
            size = float(pos.get("size", 0))
            if size == 0:
                continue
            cur_price = float(pos.get("curPrice") or pos.get("currentPrice", 0))
            if cur_price >= 0.95 or cur_price <= 0.05:
                continue
            open_positions += 1
            title = (pos.get("title") or "").lower()
            if any(w in title for w in ["counter-strike", "cs2", "dota", "league of legends", "valorant"]):
                categories["Esports"] += 1
            elif any(w in title for w in ["nba", "nfl", "nhl", "mlb", "spurs", "lakers", "celtics"]):
                categories["NBA/Sports US"] += 1
            elif any(w in title for w in ["bitcoin", "btc", "ethereum", "eth", "crypto", "price of"]):
                categories["Crypto"] += 1
            elif any(w in title for w in ["atp", "wta", "open", "tennis", "slam"]):
                categories["Tennis"] += 1
            elif any(w in title for w in ["fifa", "premier", "liga", "serie a", "win on", "spread:"]):
                categories["Football/Soccer"] += 1
            elif any(w in title for w in ["trump", "biden", "elect", "president", "congress"]):
                categories["Politics"] += 1
            else:
                categories["Other"] += 1
    except Exception:
        pass

    main_cat = categories.most_common(1)[0] if categories else ("Mixed", 0)
    cat_pct = round(main_cat[1] / open_positions * 100) if open_positions > 0 else 0

    return {
        "address": address,
        "nickname": nickname,
        "rank": rank,
        "leaderboard_pnl": leaderboard_pnl,
        "open_positions": open_positions,
        "main_category": main_cat[0],
        "category_pct": cat_pct,
        "days_since_last_trade": round(days_since, 1),
        "last_trade_ts": last_trade_ts,
        "account_age_days": account_age_days,
        "total_historical_trades": total_historical_trades,
        # Legacy fields so format_wallet_summary stays compatible
        "pnl": leaderboard_pnl,
        "roi": 0.0,
        "win_rate": 0.0,
        "wins": 0,
        "losses": 0,
        "positions": open_positions,
        "total_invested": 0.0,
        "skipped_resolved": 0,
    }


def find_profitable_wallets(markets: list[dict] = None, quiet: bool = False) -> list[dict]:
    """
    Find profitable wallets from the Polymarket leaderboard.
    `markets` param is ignored (kept for backward compatibility with telegram_commands.py).
    """
    if not quiet:
        _tprint(f"\n  Fetching Polymarket leaderboard...")

    lb_wallets = get_leaderboard_wallets(period="all")

    if not quiet:
        _tprint(f"  Found {len(lb_wallets)} wallets on leaderboard.")
        _tprint(f"  Enriching with activity data ({WALLET_WORKERS} workers)...\n")

    results = []
    done = 0
    total = len(lb_wallets)

    def _enrich(entry):
        return scan_wallet(entry["address"], leaderboard_data=entry)

    with ThreadPoolExecutor(max_workers=WALLET_WORKERS) as ex:
        futures = {ex.submit(_enrich, entry): entry for entry in lb_wallets}
        for fut in as_completed(futures):
            done += 1
            if not quiet and done % 10 == 0:
                _tprint(f"    Enriched {done}/{total}...")
            stats = fut.result()
            if stats is None:
                continue
            if stats["days_since_last_trade"] > MAX_INACTIVE_DAYS:
                continue
            if stats["account_age_days"] > 0 and stats["account_age_days"] < MIN_ACCOUNT_AGE_DAYS:
                continue
            results.append(stats)

    # Sort by leaderboard PnL (already ranked but results may be reordered by futures)
    results.sort(key=lambda x: x["leaderboard_pnl"], reverse=True)
    return results


# ── Display ───────────────────────────────────────────────────────────────────

def format_wallet_summary(w: dict) -> str:
    """Format a wallet for Telegram display."""
    addr = w["address"]
    addr_short = f"{addr[:10]}...{addr[-6:]}"
    name = w.get("nickname") or addr_short
    age = w.get("account_age_days", 0)
    total_trades = w.get("total_historical_trades", 0)
    rank = w.get("rank", 0)
    lb_pnl = w.get("leaderboard_pnl", w.get("pnl", 0))
    open_pos = w.get("open_positions", w.get("positions", 0))
    category = w.get("main_category", "Mixed")
    cat_pct = w.get("category_pct", 0)

    profile_url = f"https://polymarket.com/profile/{addr}"

    if w["days_since_last_trade"] < 1:
        active = "Hoy"
    else:
        active = f"hace {w['days_since_last_trade']:.0f}d"

    if age >= 365:
        age_str = f"{age // 365}a {(age % 365) // 30}m"
    elif age >= 30:
        age_str = f"{age // 30}m {age % 30}d"
    else:
        age_str = f"{age}d"

    rank_str = f"#{rank} " if rank else ""
    pnl_str = f"+${lb_pnl:,.0f}" if lb_pnl >= 0 else f"-${abs(lb_pnl):,.0f}"
    specialist = f"{category} ({cat_pct}%)" if cat_pct > 0 else category

    return (
        f"👤 {rank_str}<b><a href=\"{profile_url}\">{name}</a></b>\n"
        f"    <code>{addr}</code>\n"
        f"    💰 PnL (leaderboard): <b>{pnl_str}</b>\n"
        f"    🏷 Especialidad: {specialist}\n"
        f"    📈 Posiciones abiertas: {open_pos}\n"
        f"    🕐 Ultimo trade: {active}\n"
        f"    🗓 Cuenta: <b>{age_str}</b> | Trades totales: {total_trades}+"
    )


def main():
    parser = argparse.ArgumentParser(description="Find profitable Polymarket wallets from leaderboard")
    parser.add_argument("--top", type=int, default=10, help="Number of top wallets to show")
    parser.add_argument("--period", type=str, default="all", choices=["today", "weekly", "monthly", "all"],
                        help="Leaderboard period")
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 65)
    print("  Polymarket Wallet Scanner  [LEADERBOARD MODE]")
    print(f"  Source: polymarket.com/leaderboard (period={args.period})")
    print(f"  Filters: Active<{MAX_INACTIVE_DAYS}d | Age>{MIN_ACCOUNT_AGE_DAYS}d")
    print("=" * 65)

    results = find_profitable_wallets()

    elapsed = time.time() - t0
    print(f"\n{'=' * 65}")
    print(f"  Found {len(results)} wallets  ({elapsed:.0f}s)")
    print(f"{'=' * 65}\n")

    for i, w in enumerate(results[:args.top], 1):
        name = w.get("nickname") or f"{w['address'][:10]}...{w['address'][-6:]}"
        age = w.get("account_age_days", 0)
        active = "Hoy" if w["days_since_last_trade"] < 1 else f"{w['days_since_last_trade']:.0f}d ago"

        if age >= 365:
            age_str = f"{age // 365}y {(age % 365) // 30}m"
        elif age >= 30:
            age_str = f"{age // 30}m {age % 30}d"
        else:
            age_str = f"{age}d"

        print(f"  #{w.get('rank', i)} {name}")
        print(f"     Address:  {w['address']}")
        print(f"     PnL:      ${w['leaderboard_pnl']:,.0f}  (leaderboard)")
        print(f"     Category: {w['main_category']} ({w['category_pct']}%)")
        print(f"     Open pos: {w['open_positions']}")
        print(f"     Active:   {active}")
        print(f"     Account:  {age_str} old | {w['total_historical_trades']}+ total trades")
        print()

    if results:
        top = results[0]
        name = top.get("nickname") or "trader"
        print(f"  To add the top wallet:")
        print(f"  /addwallet {top['address']} {name}")

    print()


if __name__ == "__main__":
    main()
