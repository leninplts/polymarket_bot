"""Tracks copied trade outcomes and pauses copying if the trader goes cold."""

import time
import requests
import config
import telegram_notifier as tg


class ReliabilityTracker:
    def __init__(self, lookback: int = 10, min_wr: float = 0.40, check_interval: int = 900):
        """
        lookback: number of recent trades to evaluate
        min_wr: minimum win rate to keep copying (0.40 = 40%)
        check_interval: seconds between reliability checks (default 15 min)
        """
        self.lookback = lookback
        self.min_wr = min_wr
        self.check_interval = check_interval
        self.copied_trades = []  # list of {token_id, side, entry_price, timestamp}
        self.paused_wallets = set()
        self.last_check = 0

    def record_trade(self, token_id: str, side: str, entry_price: float, wallet: str):
        self.copied_trades.append({
            "token_id": token_id,
            "side": side,
            "entry_price": entry_price,
            "wallet": wallet,
            "timestamp": time.time(),
        })

    def is_wallet_paused(self, wallet: str) -> bool:
        return wallet.lower() in self.paused_wallets

    def check_reliability(self):
        """Periodically evaluate if we should keep copying each wallet."""
        now = time.time()
        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        # Group trades by wallet
        wallet_trades: dict[str, list] = {}
        for t in self.copied_trades:
            w = t["wallet"].lower()
            wallet_trades.setdefault(w, []).append(t)

        for wallet in config.TARGET_WALLETS:
            wl = wallet.lower()
            trades = wallet_trades.get(wl, [])

            if len(trades) < self.lookback:
                continue  # Not enough data yet

            recent = trades[-self.lookback:]
            wins = 0
            total_pnl = 0.0

            for t in recent:
                current_price = self._get_price(t["token_id"])
                if current_price is None:
                    continue

                if t["side"] == "BUY":
                    pnl = current_price - t["entry_price"]
                else:
                    pnl = t["entry_price"] - current_price

                total_pnl += pnl
                if pnl > 0:
                    wins += 1

            wr = wins / len(recent) if recent else 0

            was_paused = wl in self.paused_wallets

            if wr < self.min_wr:
                if not was_paused:
                    self.paused_wallets.add(wl)
                    tg.notify_trader_performance(wallet, wr, total_pnl, "pause")
                    print(f"[reliability] PAUSED {wallet[:12]}... WR={wr:.0%} PnL={total_pnl:.2f}")
            else:
                if was_paused:
                    self.paused_wallets.discard(wl)
                    tg.notify_trader_performance(wallet, wr, total_pnl, "resume")
                    print(f"[reliability] RESUMED {wallet[:12]}... WR={wr:.0%} PnL={total_pnl:.2f}")

    def _get_price(self, token_id: str) -> float | None:
        try:
            resp = requests.get(
                f"{config.CLOB_API_URL}/midpoint",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            return float(resp.json().get("mid", 0))
        except Exception:
            return None
