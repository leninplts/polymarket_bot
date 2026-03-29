"""
Demo account — simulates real trading with a virtual balance.

Shared across all wallets in 'demo' mode. Persisted to data/demo_account.json.
Mirrors the same logic as the real Trader + PositionTracker but without
any blockchain interaction.
"""

import json
import os
import time
import requests
import config

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DEMO_FILE = os.path.join(DATA_DIR, "demo_account.json")

STOP_LOSS_PCT = 0.30


class DemoAccount:
    def __init__(self, initial_balance: float = 100.0):
        self._initial_balance = initial_balance
        self._data = self._load()
        # If fresh file, set initial balance
        if "balance" not in self._data:
            self._data["balance"] = initial_balance
            self._data["initial_balance"] = initial_balance
            self._data["positions"] = []
            self._data["closed_positions"] = []
            self._save()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not os.path.exists(DEMO_FILE):
            return {}
        try:
            with open(DEMO_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        with open(DEMO_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def balance(self) -> float:
        return round(self._data.get("balance", 0), 2)

    @property
    def initial_balance(self) -> float:
        return self._data.get("initial_balance", self._initial_balance)

    @property
    def positions(self) -> list:
        return self._data.get("positions", [])

    @property
    def closed_positions(self) -> list:
        return self._data.get("closed_positions", [])

    # ── Sizing (mirrors trader._calculate_size) ───────────────────────────────

    def _calculate_size(self, price: float) -> float:
        """Calculate USDC size to invest based on price probability."""
        max_amount = config.FIXED_AMOUNT

        if price <= 0 or price >= 1:
            factor = 0.20
        elif price < 0.20:
            factor = 0.20
        elif price < 0.35:
            factor = 0.40
        elif price < 0.50:
            factor = 0.60
        elif price < 0.65:
            factor = 0.80
        elif price < 0.80:
            factor = 1.00
        else:
            factor = 0.50

        return round(max(1.0, max_amount * factor), 2)

    # ── Positions ─────────────────────────────────────────────────────────────

    def has_position(self, token_id: str) -> bool:
        return any(p["token_id"] == token_id and p["status"] == "open"
                   for p in self.positions)

    def get_position(self, token_id: str) -> dict | None:
        for p in self.positions:
            if p["token_id"] == token_id and p["status"] == "open":
                return p
        return None

    def get_invested(self, token_id: str) -> float:
        pos = self.get_position(token_id)
        if not pos:
            return 0.0
        return pos["size"] * pos["entry_price"]

    # ── Trading ───────────────────────────────────────────────────────────────

    def buy(self, token_id: str, price: float, market_name: str,
            slug: str = "", event_slug: str = "",
            source_wallet: str = "") -> dict | None:
        """
        Simulate a BUY. Deducts USDC from balance.
        Returns position dict on success, None if insufficient funds or duplicate.
        """
        if self.has_position(token_id):
            return None

        size_usdc = self._calculate_size(price)

        # Check slippage equivalent: if price > 0.95 skip (resolved market)
        if price >= 0.95 or price <= 0.05:
            return None

        if size_usdc > self.balance:
            size_usdc = round(self.balance, 2)  # use all remaining if less
            if size_usdc < 0.5:
                return None  # not enough to trade

        shares = round(size_usdc / price, 4)

        pos = {
            "token_id": token_id,
            "size": shares,
            "entry_price": price,
            "cost": size_usdc,
            "market_name": market_name,
            "slug": slug,
            "event_slug": event_slug,
            "source_wallet": source_wallet,
            "opened_at": time.time(),
            "status": "open",
        }

        self._data["balance"] = round(self.balance - size_usdc, 2)
        self._data["positions"].append(pos)
        self._save()
        return pos

    def scale(self, token_id: str, price: float) -> dict | None:
        """
        Scale into an existing demo position. Caps at MAX_POSITION_PCT of budget.
        Returns updated position dict or None if cap reached / price going down.
        """
        pos = self.get_position(token_id)
        if not pos:
            return None

        total_budget = config.FIXED_AMOUNT * 10
        max_per_market = total_budget * config.MAX_POSITION_PCT
        already_invested = self.get_invested(token_id)

        if already_invested >= max_per_market:
            return None

        if config.SCALE_ON_CONVICTION and price < pos["entry_price"]:
            return None

        room = max_per_market - already_invested
        add_usdc = min(self._calculate_size(price), room)
        add_usdc = min(add_usdc, self.balance)
        if add_usdc < 0.5:
            return None

        add_shares = round(add_usdc / price, 4)
        old_size = pos["size"]
        old_price = pos["entry_price"]
        new_total = old_size + add_shares

        pos["entry_price"] = round(
            (old_size * old_price + add_shares * price) / new_total, 6
        )
        pos["size"] = round(new_total, 4)
        pos["cost"] = round(pos["cost"] + add_usdc, 2)

        self._data["balance"] = round(self.balance - add_usdc, 2)
        self._save()
        return pos

    def sell(self, token_id: str, exit_price: float, reason: str) -> dict | None:
        """
        Simulate a SELL. Credits USDC back to balance.
        Returns closed position dict or None if not found.
        """
        for pos in self._data["positions"]:
            if pos["token_id"] == token_id and pos["status"] == "open":
                proceeds = round(pos["size"] * exit_price, 2)
                pnl = round(proceeds - pos["cost"], 2)

                pos["status"] = "closed"
                pos["exit_price"] = exit_price
                pos["closed_at"] = time.time()
                pos["close_reason"] = reason
                pos["pnl"] = pnl
                pos["proceeds"] = proceeds

                self._data["balance"] = round(self.balance + proceeds, 2)
                self._data.setdefault("closed_positions", []).append(pos)
                self._data["positions"] = [
                    p for p in self._data["positions"] if p["token_id"] != token_id
                ]
                self._save()
                return pos
        return None

    # ── Stop-loss & resolution ────────────────────────────────────────────────

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

    def check_stop_losses(self) -> list[dict]:
        """Return positions that hit the 30% stop-loss threshold."""
        triggered = []
        for pos in list(self.positions):
            if pos["status"] != "open":
                continue
            current_price = self._get_price(pos["token_id"])
            if not current_price:
                continue
            entry = pos["entry_price"]
            if entry <= 0:
                continue
            loss_pct = (entry - current_price) / entry
            if loss_pct >= STOP_LOSS_PCT:
                triggered.append({"position": pos, "current_price": current_price, "loss_pct": loss_pct})
        return triggered

    def check_resolutions(self) -> list[dict]:
        """Return positions where the market has resolved (price >= 0.95 or <= 0.05)."""
        resolved = []
        for pos in list(self.positions):
            if pos["status"] != "open":
                continue
            current_price = self._get_price(pos["token_id"])
            if not current_price:
                continue
            if current_price >= 0.95:
                resolved.append({"position": pos, "current_price": current_price, "outcome": "YES"})
            elif current_price <= 0.05:
                resolved.append({"position": pos, "current_price": current_price, "outcome": "NO"})
        return resolved

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Full account summary with unrealized PnL from live prices."""
        open_positions = [p for p in self.positions if p["status"] == "open"]
        realized_pnl = sum(p.get("pnl", 0) for p in self.closed_positions)

        unrealized_pnl = 0.0
        position_details = []
        for pos in open_positions:
            current_price = self._get_price(pos["token_id"]) or pos["entry_price"]
            pnl = round(pos["size"] * (current_price - pos["entry_price"]), 2)
            pnl_pct = round((current_price - pos["entry_price"]) / pos["entry_price"] * 100, 1) if pos["entry_price"] > 0 else 0
            unrealized_pnl += pnl
            position_details.append({
                "market_name": pos["market_name"],
                "slug": pos.get("slug", ""),
                "event_slug": pos.get("event_slug", ""),
                "entry_price": pos["entry_price"],
                "current_price": current_price,
                "size": pos["size"],
                "cost": pos["cost"],
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "source_wallet": pos.get("source_wallet", ""),
            })

        total_pnl = round(realized_pnl + unrealized_pnl, 2)
        total_return_pct = round(total_pnl / self.initial_balance * 100, 1) if self.initial_balance > 0 else 0

        return {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "in_positions": round(sum(p["cost"] for p in open_positions), 2),
            "open_count": len(open_positions),
            "closed_count": len(self.closed_positions),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": total_pnl,
            "total_return_pct": total_return_pct,
            "positions": position_details,
        }

    def reset(self, initial_balance: float = None):
        """Reset the demo account to a fresh state."""
        bal = initial_balance or self.initial_balance
        self._data = {
            "balance": bal,
            "initial_balance": bal,
            "positions": [],
            "closed_positions": [],
        }
        self._save()
