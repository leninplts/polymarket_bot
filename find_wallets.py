"""
Utility to find profitable wallets on Polymarket.

Scans recent activity on popular markets to identify wallets
with consistent winning trades.

Usage:
    python find_wallets.py                    # Scan top markets
    python find_wallets.py --market <slug>    # Scan a specific market
"""

import argparse
import requests
from collections import defaultdict

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"


def get_top_markets(limit: int = 10) -> list[dict]:
    """Fetch the most active markets."""
    resp = requests.get(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "order": "volume", "ascending": "false", "active": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def scan_wallet(address: str) -> dict:
    """Analyze a wallet's trading performance."""
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": address},
            timeout=15,
        )
        resp.raise_for_status()
        positions = resp.json()
    except Exception:
        return {"address": address, "positions": 0, "pnl": 0, "win_rate": 0}

    wins = 0
    total = 0
    total_pnl = 0.0

    for pos in positions:
        size = float(pos.get("size", 0))
        if size == 0:
            continue

        avg_price = float(pos.get("avgPrice", 0))
        cur_price = float(pos.get("curPrice") or pos.get("currentPrice", 0))
        pnl = size * (cur_price - avg_price)
        total_pnl += pnl
        total += 1

        if pnl > 0:
            wins += 1

    return {
        "address": address,
        "positions": total,
        "pnl": round(total_pnl, 2),
        "win_rate": round(wins / total, 2) if total > 0 else 0,
    }


def find_active_traders(markets: list[dict], min_positions: int = 3) -> list[dict]:
    """Find wallets that appear across multiple markets with good performance."""
    # Collect unique traders from market trades
    trader_addresses = set()

    for market in markets:
        slug = market.get("slug", "")
        condition_id = market.get("conditionId", "")
        print(f"  Scanning: {market.get('question', slug)[:60]}...")

        try:
            resp = requests.get(
                f"{DATA_API}/trades",
                params={"market": condition_id, "limit": 100},
                timeout=15,
            )
            resp.raise_for_status()
            trades = resp.json()

            for trade in trades:
                addr = trade.get("proxyWallet")
                if addr:
                    trader_addresses.add(addr.lower())
            print(f"    Found {len(trades)} trades")
        except Exception as e:
            print(f"    Error: {e}")

    print(f"\n  Found {len(trader_addresses)} unique traders. Analyzing...")

    # Analyze each trader
    results = []
    for i, addr in enumerate(trader_addresses):
        if (i + 1) % 20 == 0:
            print(f"    Analyzed {i + 1}/{len(trader_addresses)}...")
        stats = scan_wallet(addr)
        if stats["positions"] >= min_positions:
            results.append(stats)

    # Sort by PnL
    results.sort(key=lambda x: x["pnl"], reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Find profitable Polymarket wallets")
    parser.add_argument("--limit", type=int, default=5, help="Number of top markets to scan")
    parser.add_argument("--min-positions", type=int, default=3, help="Minimum positions to include")
    parser.add_argument("--top", type=int, default=20, help="Number of top wallets to show")
    args = parser.parse_args()

    print("=" * 60)
    print("  Polymarket Wallet Scanner")
    print("=" * 60)
    print(f"\n  Fetching top {args.limit} markets by volume...\n")

    markets = get_top_markets(args.limit)
    results = find_active_traders(markets, min_positions=args.min_positions)

    print(f"\n{'=' * 60}")
    print(f"  Top {args.top} Profitable Wallets")
    print(f"{'=' * 60}\n")
    print(f"  {'Wallet':<46} {'Pos':>4} {'WR':>5} {'PnL':>10}")
    print(f"  {'-' * 46} {'-' * 4} {'-' * 5} {'-' * 10}")

    for w in results[: args.top]:
        addr = f"{w['address'][:10]}...{w['address'][-6:]}"
        print(f"  {addr:<46} {w['positions']:>4} {w['win_rate']:>4.0%} ${w['pnl']:>9.2f}")

    if results:
        print(f"\n  Copy-paste for .env TARGET_WALLETS:")
        top_addrs = ",".join(w["address"] for w in results[: min(5, args.top)])
        print(f"  TARGET_WALLETS={top_addrs}")

    print()


if __name__ == "__main__":
    main()
