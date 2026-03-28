"""Tracks our open positions for stop-loss and exit copying."""

import json
import os
import time
import requests
import config

POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")

# Stop-loss: close if position drops more than this % from entry
STOP_LOSS_PCT = 0.30  # 30%


class PositionTracker:
    def __init__(self):
        self.positions = self._load()

    def _load(self) -> list[dict]:
        if not os.path.exists(POSITIONS_FILE):
            return []
        try:
            with open(POSITIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self):
        with open(POSITIONS_FILE, "w") as f:
            json.dump(self.positions, f, indent=2)

    def add_position(self, token_id: str, side: str, size: float,
                     entry_price: float, market_name: str,
                     slug: str = "", event_slug: str = "",
                     source_wallet: str = ""):
        """Record a new open position."""
        self.positions.append({
            "token_id": token_id,
            "side": side,
            "size": size,
            "entry_price": entry_price,
            "market_name": market_name,
            "slug": slug,
            "event_slug": event_slug,
            "source_wallet": source_wallet,
            "opened_at": time.time(),
            "status": "open",
        })
        self._save()

    def close_position(self, token_id: str, exit_price: float, reason: str) -> dict | None:
        """Mark a position as closed and return it."""
        for pos in self.positions:
            if pos["token_id"] == token_id and pos["status"] == "open":
                pos["status"] = "closed"
                pos["exit_price"] = exit_price
                pos["closed_at"] = time.time()
                pos["close_reason"] = reason
                pos["pnl"] = self._calc_pnl(pos, exit_price)
                self._save()
                return pos
        return None

    def get_open_positions(self) -> list[dict]:
        return [p for p in self.positions if p["status"] == "open"]

    def get_closed_positions(self) -> list[dict]:
        return [p for p in self.positions if p["status"] == "closed"]

    def has_position(self, token_id: str) -> bool:
        return any(p["token_id"] == token_id and p["status"] == "open"
                   for p in self.positions)

    def _calc_pnl(self, pos: dict, current_price: float) -> float:
        entry = pos["entry_price"]
        size = pos["size"]
        if pos["side"] == "BUY":
            return round(size * (current_price - entry), 2)
        else:
            return round(size * (entry - current_price), 2)

    def check_stop_losses(self) -> list[dict]:
        """Check all open positions against stop-loss. Returns positions that hit SL."""
        triggered = []

        for pos in self.positions:
            if pos["status"] != "open":
                continue

            token_id = pos["token_id"]
            current_price = self._get_price(token_id)
            if current_price is None:
                continue

            entry = pos["entry_price"]
            if entry <= 0:
                continue

            # Calculate loss percentage
            if pos["side"] == "BUY":
                loss_pct = (entry - current_price) / entry
            else:
                loss_pct = (current_price - entry) / entry

            if loss_pct >= STOP_LOSS_PCT:
                triggered.append({
                    "position": pos,
                    "current_price": current_price,
                    "loss_pct": loss_pct,
                })

        return triggered

    def get_portfolio_summary(self) -> dict:
        """Get summary of all open positions with current prices."""
        open_pos = self.get_open_positions()
        total_pnl = 0.0
        total_invested = 0.0
        details = []

        for pos in open_pos:
            current_price = self._get_price(pos["token_id"])
            if current_price is None:
                current_price = pos["entry_price"]

            pnl = self._calc_pnl(pos, current_price)
            invested = pos["size"] * pos["entry_price"]
            total_pnl += pnl
            total_invested += invested

            pnl_pct = (pnl / invested * 100) if invested > 0 else 0

            details.append({
                "market_name": pos["market_name"],
                "slug": pos.get("slug", ""),
                "event_slug": pos.get("event_slug", ""),
                "side": pos["side"],
                "size": pos["size"],
                "entry_price": pos["entry_price"],
                "current_price": current_price,
                "pnl": pnl,
                "pnl_pct": round(pnl_pct, 1),
                "token_id": pos["token_id"],
            })

        closed = self.get_closed_positions()
        realized_pnl = sum(p.get("pnl", 0) for p in closed)

        return {
            "open_count": len(open_pos),
            "total_invested": round(total_invested, 2),
            "unrealized_pnl": round(total_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "total_pnl": round(total_pnl + realized_pnl, 2),
            "positions": details,
        }

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
