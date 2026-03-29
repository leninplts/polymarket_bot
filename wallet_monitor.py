"""Monitor target wallets for new trades via the Polymarket Data API."""

import time
import requests
import config


class WalletMonitor:
    def __init__(self, wallets: list[str]):
        self.wallets = wallets
        # Track the latest seen transaction hashes per wallet to avoid duplicates.
        # Using a set of hashes is reliable since hashes are unique per trade.
        self._seen_hashes: dict[str, set] = {}
        # Also track latest timestamp per wallet (for ordering)
        self._last_ts: dict[str, float] = {}

    def _fetch_activity(self, wallet: str) -> list[dict]:
        """Fetch recent trade activity for a wallet."""
        try:
            resp = requests.get(
                f"{config.DATA_API_URL}/activity",
                params={"user": wallet},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[monitor] Error fetching activity for {wallet}: {e}")
            return []

    def _fetch_positions(self, wallet: str) -> list[dict]:
        """Fetch current positions for a wallet."""
        try:
            resp = requests.get(
                f"{config.DATA_API_URL}/positions",
                params={"user": wallet},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[monitor] Error fetching positions for {wallet}: {e}")
            return []

    def get_new_trades(self) -> list[dict]:
        """Poll all target wallets and return any new trades since last check."""
        new_trades = []

        for wallet in self.wallets:
            activities = self._fetch_activity(wallet)
            if not activities:
                continue

            seen = self._seen_hashes.setdefault(wallet, set())
            last_ts = self._last_ts.get(wallet, 0)

            # First call: seed seen hashes from existing activity so we don't
            # replay old trades on startup.
            first_run = (last_ts == 0)

            for activity in activities:
                ts = float(activity.get("timestamp") or activity.get("createdAt") or 0)
                tx_hash = activity.get("transactionHash") or activity.get("id") or str(ts)

                # Stop iterating once we reach trades older than what we've seen
                if ts < last_ts:
                    break

                # Skip already-processed trades (handles same-timestamp batches)
                if tx_hash in seen:
                    continue

                seen.add(tx_hash)

                # On first run just seed the set — don't emit trades
                if first_run:
                    continue

                # Only process BUY/SELL trades (skip deposits, withdrawals, etc.)
                action = (activity.get("type") or activity.get("action") or "").upper()
                if action not in ("BUY", "SELL", "TRADE"):
                    continue

                price = float(activity.get("price", 0))

                # Skip trades at extreme prices — these are cashouts of
                # resolved markets (buying at 0.99+ or selling at 0.01-),
                # not real entries with upside.
                if price >= 0.95 or price <= 0.05:
                    continue

                new_trades.append({
                    "wallet": wallet,
                    "trade_id": tx_hash,
                    "action": action,
                    "side": activity.get("side", "").upper(),
                    "asset": activity.get("asset"),
                    "token_id": activity.get("tokenId") or activity.get("asset"),
                    "condition_id": activity.get("conditionId"),
                    "market_slug": activity.get("market_slug") or activity.get("slug"),
                    "size": float(activity.get("size", 0)),
                    "price": float(activity.get("price", 0)),
                    "outcome": activity.get("outcome") or activity.get("title"),
                    "timestamp": ts,
                    "raw": activity,
                })

            # Update last seen timestamp to the most recent activity
            if activities:
                newest_ts = float(activities[0].get("timestamp") or activities[0].get("createdAt") or 0)
                if newest_ts > last_ts:
                    self._last_ts[wallet] = newest_ts

        return new_trades

    def get_wallet_pnl(self, wallet: str) -> dict:
        """Get a summary of a wallet's current positions and estimated PnL."""
        positions = self._fetch_positions(wallet)
        total_value = 0.0
        total_cost = 0.0

        for pos in positions:
            size = float(pos.get("size", 0))
            avg_price = float(pos.get("avgPrice", 0))
            cur_price = float(pos.get("curPrice") or pos.get("currentPrice", 0))
            total_cost += size * avg_price
            total_value += size * cur_price

        return {
            "wallet": wallet,
            "positions": len(positions),
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(total_value - total_cost, 2),
        }
