"""
Polymarket Wallet Scanner

Finds profitable wallets based on:
- PnL > $500
- Win rate > 55%
- Minimum 10 positions
- Active in last 7 days
- Shows main category and nickname

Can run standalone or be called by the bot for auto-scanning.
"""

import time
import argparse
import requests
from collections import Counter
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Filters
MIN_PNL = 500
MIN_WIN_RATE = 0.55
MIN_POSITIONS = 10
MAX_INACTIVE_DAYS = 7


def get_top_markets(limit: int = 15) -> list[dict]:
    """Fetch the most active markets."""
    resp = requests.get(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "order": "volume", "ascending": "false", "active": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _get_nickname(address: str) -> str:
    """Fetch the user's display name from their activity."""
    try:
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0].get("name") or data[0].get("pseudonym") or ""
    except Exception:
        pass
    return ""


def _get_last_trade_time(address: str) -> float:
    """Get timestamp of most recent trade."""
    try:
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0].get("timestamp", 0))
    except Exception:
        pass
    return 0


def scan_wallet(address: str) -> dict:
    """Deep analysis of a wallet's trading performance."""
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": address},
            timeout=15,
        )
        resp.raise_for_status()
        positions = resp.json()
    except Exception:
        return None

    if not positions:
        return None

    wins = 0
    losses = 0
    total_pnl = 0.0
    total_invested = 0.0
    categories = Counter()

    for pos in positions:
        size = float(pos.get("size", 0))
        if size == 0:
            continue

        avg_price = float(pos.get("avgPrice", 0))
        cur_price = float(pos.get("curPrice") or pos.get("currentPrice", 0))
        invested = size * avg_price
        pnl = size * (cur_price - avg_price)
        total_pnl += pnl
        total_invested += invested

        if pnl > 0:
            wins += 1
        else:
            losses += 1

        # Detect category from title
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

    total = wins + losses
    if total == 0:
        return None

    win_rate = wins / total
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # Main category
    main_cat = categories.most_common(1)[0] if categories else ("Unknown", 0)
    cat_pct = main_cat[1] / total if total > 0 else 0

    # Get nickname and last activity
    nickname = _get_nickname(address)
    last_trade = _get_last_trade_time(address)
    days_since = (time.time() - last_trade) / 86400 if last_trade > 0 else 999

    return {
        "address": address,
        "nickname": nickname,
        "positions": total,
        "wins": wins,
        "losses": losses,
        "pnl": round(total_pnl, 2),
        "roi": round(roi, 1),
        "win_rate": round(win_rate, 2),
        "total_invested": round(total_invested, 2),
        "main_category": main_cat[0],
        "category_pct": round(cat_pct * 100),
        "days_since_last_trade": round(days_since, 1),
        "last_trade_ts": last_trade,
    }


def find_profitable_wallets(markets: list[dict], quiet: bool = False) -> list[dict]:
    """Find wallets matching our criteria from active markets."""
    trader_addresses = set()

    for market in markets:
        slug = market.get("slug", "")
        condition_id = market.get("conditionId", "")
        if not quiet:
            print(f"  Scanning: {market.get('question', slug)[:60]}...")

        try:
            # Get more trades for better coverage
            for offset in [0, 100]:
                resp = requests.get(
                    f"{DATA_API}/trades",
                    params={"market": condition_id, "limit": 100, "offset": offset},
                    timeout=15,
                )
                resp.raise_for_status()
                trades = resp.json()
                for trade in trades:
                    addr = trade.get("proxyWallet")
                    if addr:
                        trader_addresses.add(addr.lower())

            if not quiet:
                print(f"    OK")
        except Exception as e:
            if not quiet:
                print(f"    Error: {e}")

    if not quiet:
        print(f"\n  Found {len(trader_addresses)} unique traders. Analyzing...\n")

    results = []
    for i, addr in enumerate(trader_addresses):
        if not quiet and (i + 1) % 20 == 0:
            print(f"    Analyzed {i + 1}/{len(trader_addresses)}...")

        stats = scan_wallet(addr)
        if stats is None:
            continue

        # Apply filters
        if stats["positions"] < MIN_POSITIONS:
            continue
        if stats["pnl"] < MIN_PNL:
            continue
        if stats["win_rate"] < MIN_WIN_RATE:
            continue
        if stats["days_since_last_trade"] > MAX_INACTIVE_DAYS:
            continue

        results.append(stats)

    # Sort by PnL
    results.sort(key=lambda x: x["pnl"], reverse=True)
    return results


def format_wallet_summary(w: dict) -> str:
    """Format a wallet for display."""
    addr_short = f"{w['address'][:10]}...{w['address'][-6:]}"
    name = w.get("nickname") or addr_short
    specialist = f"{w['main_category']} ({w['category_pct']}%)"
    active = f"{w['days_since_last_trade']:.0f}d ago" if w["days_since_last_trade"] < 1 else f"{w['days_since_last_trade']:.0f}d ago"
    if w["days_since_last_trade"] < 1:
        active = "Hoy"

    return (
        f"👤 <b>{name}</b>\n"
        f"    <code>{w['address']}</code>\n"
        f"    💰 PnL: <b>${w['pnl']:,.2f}</b> (ROI: {w['roi']}%)\n"
        f"    📊 Win rate: <b>{w['win_rate']:.0%}</b> ({w['wins']}W / {w['losses']}L)\n"
        f"    🏷 Especialidad: {specialist}\n"
        f"    📈 Posiciones: {w['positions']} | Invertido: ${w['total_invested']:,.0f}\n"
        f"    🕐 Ultimo trade: {active}"
    )


def main():
    parser = argparse.ArgumentParser(description="Find profitable Polymarket wallets")
    parser.add_argument("--limit", type=int, default=15, help="Number of top markets to scan")
    parser.add_argument("--top", type=int, default=10, help="Number of top wallets to show")
    args = parser.parse_args()

    print("=" * 60)
    print("  Polymarket Wallet Scanner")
    print(f"  Filters: PnL>${MIN_PNL} | WR>{MIN_WIN_RATE:.0%} | Pos>{MIN_POSITIONS} | Active<{MAX_INACTIVE_DAYS}d")
    print("=" * 60)
    print(f"\n  Fetching top {args.limit} markets by volume...\n")

    markets = get_top_markets(args.limit)
    results = find_profitable_wallets(markets)

    print(f"\n{'=' * 60}")
    print(f"  Found {len(results)} wallets matching criteria")
    print(f"{'=' * 60}\n")

    for i, w in enumerate(results[:args.top], 1):
        name = w.get("nickname") or f"{w['address'][:10]}...{w['address'][-6:]}"
        specialist = f"{w['main_category']} ({w['category_pct']}%)"
        active = "Hoy" if w["days_since_last_trade"] < 1 else f"{w['days_since_last_trade']:.0f}d"

        print(f"  #{i} {name}")
        print(f"     Address:  {w['address']}")
        print(f"     PnL:      ${w['pnl']:,.2f} (ROI: {w['roi']}%)")
        print(f"     Win rate: {w['win_rate']:.0%} ({w['wins']}W / {w['losses']}L)")
        print(f"     Focus:    {specialist}")
        print(f"     Invested: ${w['total_invested']:,.0f} | Positions: {w['positions']}")
        print(f"     Active:   {active}")
        print()

    if results:
        print(f"  To add the top wallet:")
        top = results[0]
        name = top.get("nickname") or "trader"
        print(f"  /addwallet {top['address']} {name}")

    print()


if __name__ == "__main__":
    main()
