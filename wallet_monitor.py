"""Monitor target wallets for new trades via the Polymarket Data API."""

import time
import requests
import config


class WalletMonitor:
    def __init__(self, wallets: list[str]):
        self.wallets = wallets
        # Track the latest trade timestamp per wallet to avoid duplicates
        self._last_seen: dict[str, str] = {}

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

            last_seen = self._last_seen.get(wallet)

            for activity in activities:
                # Activity items have a timestamp field
                ts = activity.get("timestamp") or activity.get("createdAt") or ""
                trade_id = activity.get("transactionHash") or activity.get("id") or ts

                if last_seen and trade_id <= last_seen:
                    break

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
                    "trade_id": trade_id,
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

            # Update last seen to the most recent trade
            if activities:
                first = activities[0]
                first_id = first.get("transactionHash") or first.get("id") or first.get("timestamp", "")
                if not last_seen or first_id > last_seen:
                    self._last_seen[wallet] = first_id

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
