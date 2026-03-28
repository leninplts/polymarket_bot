"""
Polymarket Wallet Scanner

Finds profitable wallets based on:
- PnL > $500
- Win rate > 55%
- Minimum 10 positions
- Active in last 7 days
- Account age > 30 days (anti-survivorship bias)
- Shows main category, nickname, account age

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
MIN_ACCOUNT_AGE_DAYS = 30  # Minimum account age to filter out fresh "lucky" wallets


def get_top_markets(limit: int = 50) -> list[dict]:
    """Fetch the most active markets."""
    resp = requests.get(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "order": "volume", "ascending": "false", "active": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _get_profile(address: str) -> dict:
    """Fetch nickname and first trade timestamp from activity history."""
    nickname = ""
    first_trade_ts = 0
    total_historical_trades = 0

    try:
        # Get most recent activity for nickname
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

    # Get oldest activity to determine account age
    # We paginate backwards to find the first trade
    try:
        # First check how many trades roughly (get a high offset)
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
                # Keep going to find even older
            else:
                break

        # If we found trades at offset 500, try to find the actual oldest
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


def _get_closed_pnl(address: str) -> float:
    """Estimate PnL from closed/resolved positions via activity history."""
    closed_pnl = 0.0
    try:
        # Get recent activity to find resolved trades (price ~1.0 or ~0.0)
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 100},
            timeout=15,
        )
        resp.raise_for_status()
        activities = resp.json()

        for act in activities:
            price = float(act.get("price", 0))
            size = float(act.get("size", 0))
            side = (act.get("side") or "").upper()

            # Resolved market cashouts: buying at ~1.0 means collecting winnings
            # The actual profit was from the original entry, not the cashout
            # We skip these as they're already reflected in positions or hard to calculate
            # But selling at ~1.0 on a BUY position = realized gain
            if side == "SELL" and price >= 0.95:
                closed_pnl += size * (price - 0.5)  # rough estimate
    except Exception:
        pass

    return round(closed_pnl, 2)


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

    # Get profile: nickname, account age, total trades
    profile = _get_profile(address)
    nickname = profile["nickname"]
    first_trade_ts = profile["first_trade_ts"]
    total_historical_trades = profile["total_historical_trades"]

    # Calculate account age
    if first_trade_ts > 0:
        account_age_days = (time.time() - first_trade_ts) / 86400
    else:
        account_age_days = 0

    # Get last trade time from most recent activity
    last_trade_ts = 0
    try:
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            last_trade_ts = float(data[0].get("timestamp", 0))
    except Exception:
        pass
    days_since = (time.time() - last_trade_ts) / 86400 if last_trade_ts > 0 else 999

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
        "last_trade_ts": last_trade_ts,
        "account_age_days": round(account_age_days),
        "total_historical_trades": total_historical_trades,
        "first_trade_ts": first_trade_ts,
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
            # 5 pages of 100 = 500 trades per market
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
        if not quiet and (i + 1) % 25 == 0:
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
        if stats["account_age_days"] < MIN_ACCOUNT_AGE_DAYS:
            continue

        results.append(stats)

    # Sort by PnL
    results.sort(key=lambda x: x["pnl"], reverse=True)
    return results


def format_wallet_summary(w: dict) -> str:
    """Format a wallet for Telegram display."""
    addr_short = f"{w['address'][:10]}...{w['address'][-6:]}"
    name = w.get("nickname") or addr_short
    specialist = f"{w['main_category']} ({w['category_pct']}%)"
    age = w.get("account_age_days", 0)
    total_trades = w.get("total_historical_trades", 0)

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

    # Trust score: simple heuristic
    trust = 0
    if age >= 180:
        trust += 3
    elif age >= 90:
        trust += 2
    elif age >= 30:
        trust += 1
    if w["win_rate"] >= 0.65:
        trust += 2
    elif w["win_rate"] >= 0.55:
        trust += 1
    if total_trades >= 200:
        trust += 2
    elif total_trades >= 50:
        trust += 1
    if w["roi"] >= 10:
        trust += 1

    trust_bar = "🟢" * min(trust, 5) + "⚪" * max(5 - trust, 0)

    return (
        f"👤 <b>{name}</b>  {trust_bar}\n"
        f"    <code>{w['address']}</code>\n"
        f"    💰 PnL: <b>${w['pnl']:,.2f}</b> (ROI: {w['roi']}%)\n"
        f"    📊 WR: <b>{w['win_rate']:.0%}</b> ({w['wins']}W/{w['losses']}L)\n"
        f"    🏷 Especialidad: {specialist}\n"
        f"    📈 Posiciones: {w['positions']} | Invertido: ${w['total_invested']:,.0f}\n"
        f"    🕐 Ultimo trade: {active}\n"
        f"    🗓 Cuenta: <b>{age_str}</b> | Trades totales: {total_trades}+"
    )


def main():
    parser = argparse.ArgumentParser(description="Find profitable Polymarket wallets")
    parser.add_argument("--limit", type=int, default=50, help="Number of top markets to scan")
    parser.add_argument("--top", type=int, default=10, help="Number of top wallets to show")
    args = parser.parse_args()

    print("=" * 65)
    print("  Polymarket Wallet Scanner")
    print(f"  Filters: PnL>${MIN_PNL} | WR>{MIN_WIN_RATE:.0%} | Pos>{MIN_POSITIONS} | Active<{MAX_INACTIVE_DAYS}d | Age>{MIN_ACCOUNT_AGE_DAYS}d")
    print("=" * 65)
    print(f"\n  Fetching top {args.limit} markets by volume...\n")

    markets = get_top_markets(args.limit)
    results = find_profitable_wallets(markets)

    print(f"\n{'=' * 65}")
    print(f"  Found {len(results)} wallets matching criteria")
    print(f"{'=' * 65}\n")

    for i, w in enumerate(results[:args.top], 1):
        name = w.get("nickname") or f"{w['address'][:10]}...{w['address'][-6:]}"
        specialist = f"{w['main_category']} ({w['category_pct']}%)"
        age = w.get("account_age_days", 0)
        active = "Hoy" if w["days_since_last_trade"] < 1 else f"{w['days_since_last_trade']:.0f}d ago"

        if age >= 365:
            age_str = f"{age // 365}y {(age % 365) // 30}m"
        elif age >= 30:
            age_str = f"{age // 30}m {age % 30}d"
        else:
            age_str = f"{age}d"

        print(f"  #{i} {name}")
        print(f"     Address:    {w['address']}")
        print(f"     PnL:        ${w['pnl']:,.2f} (ROI: {w['roi']}%)")
        print(f"     Win rate:   {w['win_rate']:.0%} ({w['wins']}W / {w['losses']}L)")
        print(f"     Focus:      {specialist}")
        print(f"     Invested:   ${w['total_invested']:,.0f} | Positions: {w['positions']}")
        print(f"     Active:     {active}")
        print(f"     Account:    {age_str} old | {w['total_historical_trades']}+ total trades")
        print()

    if results:
        print(f"  To add the top wallet:")
        top = results[0]
        name = top.get("nickname") or "trader"
        print(f"  /addwallet {top['address']} {name}")

    print()


if __name__ == "__main__":
    main()
