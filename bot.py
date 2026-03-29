"""
Polymarket Copy-Trading Bot

Monitors profitable wallets and copies their trades on Polymarket.
Starts in DRY RUN by default — use /live from Telegram to activate.

Exit strategy:
  - Copies trader's exits (if they sell, we sell)
  - Stop-loss at 30% as safety net
  - No take-profit limit (let profits run)

Usage:
    python bot.py              # Run in dry-run (default, safe)
    python bot.py --live       # Run in live mode (real trades)
    python bot.py --status     # Show target wallet positions/PnL
"""

import sys
import time
import signal
import argparse
from datetime import datetime

import config
import wallet_manager
from wallet_monitor import WalletMonitor
from trader import Trader
from position_tracker import PositionTracker
import market_cache
import telegram_notifier as tg
from telegram_commands import TelegramCommands
from reliability_tracker import ReliabilityTracker

SUMMARY_INTERVAL = 1800  # 30 minutes
STOP_LOSS_CHECK_INTERVAL = 60  # Check stop-losses every 60 seconds
TRADE_BUFFER_WINDOW = 60  # Seconds to aggregate fragmented orders from same market


class CopyTradingBot:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        wallet_manager.init_from_config(config.TARGET_WALLETS)
        self.monitor = WalletMonitor(wallet_manager.get_addresses())
        self.trader = None if dry_run else Trader()
        self.positions = PositionTracker()
        self.running = False
        self.stats = {"trades_detected": 0, "trades_copied": 0, "trades_skipped": 0, "exits_copied": 0, "stop_losses": 0}
        self.skipped_trades = []
        self.last_summary = 0
        self.last_sl_check = 0
        # Buffer for aggregating fragmented orders: key = (wallet, condition_id)
        # value = {first_trade, total_size, total_usdc, count, first_seen, last_seen, notified_first}
        self._trade_buffer: dict = {}
        self.commands = TelegramCommands(self)
        self.reliability = ReliabilityTracker()

    def _print_header(self):
        mode = "DRY RUN" if self.dry_run else "LIVE"
        wallets = wallet_manager.get_all()
        open_pos = self.positions.get_open_positions()
        print("=" * 60)
        print(f"  Polymarket Copy-Trading Bot [{mode}]")
        print(f"  Monitoring {len(wallets)} wallet(s)")
        print(f"  Open positions: {len(open_pos)}")
        print(f"  Sizing: dynamic (max ${config.FIXED_AMOUNT} based on probability)")
        print(f"  Stop-loss: 30% | Take-profit: none (unlimited)")
        print(f"  Max slippage: {config.MAX_SLIPPAGE:.1%}")
        print(f"  Poll interval: {config.POLL_INTERVAL}s")
        print("=" * 60)

        for w in wallets:
            nick = w.get("nickname") or f"{w['address'][:10]}...{w['address'][-6:]}"
            print(f"  Tracking: {nick} ({w['address'][:10]}...{w['address'][-6:]})")
        print()

    def _get_market_info(self, trade: dict) -> tuple[str, str, str]:
        """Returns (market_name, slug, event_slug) for a trade."""
        market = None
        if trade.get("token_id"):
            market = market_cache.get_market_by_token(trade["token_id"])
        elif trade.get("condition_id"):
            market = market_cache.get_market(trade["condition_id"])

        if market:
            return (
                market.get("question", "Unknown"),
                market.get("slug", ""),
                market.get("eventSlug", "") or market.get("event_slug", ""),
            )
        return ("Unknown", "", "")

    def _handle_trade(self, trade: dict):
        """
        Process a detected trade.
        BUYs go through the aggregation buffer to collapse fragmented orders.
        SELLs are processed immediately.
        """
        self.stats["trades_detected"] += 1
        side = trade.get("side", "BUY")
        token_id = trade.get("token_id", "")
        condition_id = trade.get("condition_id", "") or token_id

        # SELLs: always immediate — exits are time-critical
        if side == "SELL":
            market_name, slug, event_slug = self._get_market_info(trade)
            if token_id and self.positions.has_position(token_id):
                tg.notify_trade_detected(trade, market_name, slug, event_slug)
                self._handle_exit(trade, market_name, slug, event_slug)
            return

        # BUYs: aggregate into buffer
        buf_key = (trade.get("wallet", ""), condition_id)
        now = time.time()

        if buf_key not in self._trade_buffer:
            # First order for this market — notify immediately and open entry
            market_name, slug, event_slug = self._get_market_info(trade)
            self._trade_buffer[buf_key] = {
                "first_trade": trade,
                "market_name": market_name,
                "slug": slug,
                "event_slug": event_slug,
                "total_size": float(trade.get("size", 0)),
                "total_usdc": float(trade.get("raw", {}).get("usdcSize", 0)),
                "count": 1,
                "first_seen": now,
                "last_price": float(trade.get("price", 0)),
            }
            wallet_short = f"{trade['wallet'][:10]}...{trade['wallet'][-6:]}"
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] TRADE DETECTED from {wallet_short}")
            print(f"  Market:  {market_name}")
            print(f"  Side:    {side} (primera orden, buffer abierto 60s)")
            print(f"  Price:   {trade.get('price', '?')}")

            tg.notify_trade_detected(trade, market_name, slug, event_slug)
            self._execute_buy(trade, market_name, slug, event_slug)
        else:
            # Subsequent order for same market — accumulate and attempt to scale
            buf = self._trade_buffer[buf_key]
            buf["total_size"] += float(trade.get("size", 0))
            buf["total_usdc"] += float(trade.get("raw", {}).get("usdcSize", 0))
            buf["count"] += 1
            new_price = float(trade.get("price", 0))
            buf["last_price"] = new_price

            # Try to scale into the position if conditions allow
            self._try_scale(trade, buf, new_price)

    def _try_scale(self, trade: dict, buf: dict, new_price: float):
        """
        Try to add to an existing position when the trader keeps buying the same market.

        Rules:
        1. We must already have the position open
        2. Total invested in this market must be below MAX_POSITION_PCT * budget
        3. If SCALE_ON_CONVICTION=true, new price must be >= our avg entry (price going up)
           — avoids averaging down on losing positions
        4. Not in dry_run (can't execute real trades)
        """
        if self.dry_run:
            return

        token_id = trade.get("token_id", "")
        if not token_id:
            return

        pos = self.positions.get_position(token_id)
        if not pos:
            return  # We don't have this position, normal entry already handled

        # Budget cap: FIXED_AMOUNT * 10 is our assumed total budget for sizing
        total_budget = config.FIXED_AMOUNT * 10
        max_per_market = total_budget * config.MAX_POSITION_PCT
        already_invested = self.positions.get_invested(token_id)

        if already_invested >= max_per_market:
            print(
                f"  [scale] Skipped — already at max position "
                f"(${already_invested:.2f} >= ${max_per_market:.2f})"
            )
            return

        # Conviction check: only scale if price is going up
        if config.SCALE_ON_CONVICTION and new_price < pos["entry_price"]:
            print(
                f"  [scale] Skipped — price going down "
                f"({new_price:.3f} < entry {pos['entry_price']:.3f}), "
                f"not averaging down"
            )
            return

        # Calculate how much more we can add without exceeding the cap
        room = max_per_market - already_invested
        scale_size = self.trader._calculate_size(trade.get("size", 0), new_price)
        scale_size = min(scale_size, room / max(new_price, 0.01))  # cap to remaining room
        scale_size = round(scale_size, 2)

        if scale_size < 1:
            return  # Too small to bother

        market_name = buf["market_name"]
        slug = buf["slug"]
        event_slug = buf["event_slug"]

        result = self.trader.execute_copy_trade({**trade, "size": scale_size})
        if result:
            self.stats["trades_copied"] += 1
            updated = self.positions.add_to_position(token_id, scale_size, new_price)
            new_avg = updated["entry_price"] if updated else new_price
            new_total = updated["size"] if updated else pos["size"] + scale_size
            invested_now = new_total * new_avg

            print(
                f"  [scale] SCALED +${scale_size * new_price:.2f} @ {new_price:.3f} | "
                f"avg entry now {new_avg:.3f} | total invested ${invested_now:.2f}"
            )
            tg.notify_trade_scaled(
                wallet_manager.get_nickname(trade.get("wallet", "")),
                market_name, scale_size, new_price, new_avg,
                invested_now, max_per_market,
                slug, event_slug,
            )
        else:
            print(f"  [scale] Scale order failed for {market_name}")

    def _flush_trade_buffers(self):
        """
        Every poll cycle: flush buffers older than TRADE_BUFFER_WINDOW.
        Sends a summary message if there were multiple orders.
        """
        now = time.time()
        to_delete = []

        for buf_key, buf in self._trade_buffer.items():
            if now - buf["first_seen"] < TRADE_BUFFER_WINDOW:
                continue

            to_delete.append(buf_key)

            if buf["count"] > 1:
                wallet, _ = buf_key
                nick = wallet_manager.get_nickname(wallet)
                market_name = buf["market_name"]
                total_usdc = buf["total_usdc"]
                total_size = buf["total_size"]
                count = buf["count"]
                last_price = buf["last_price"]

                print(f"\n[buffer] {nick} — {market_name}: {count} ordenes, ${total_usdc:.2f} USDC total")
                tg.notify_trade_buffer_summary(
                    nick, market_name, count, total_usdc, total_size,
                    buf["first_trade"].get("price", 0), last_price,
                    buf["slug"], buf["event_slug"],
                )

        for k in to_delete:
            del self._trade_buffer[k]

    def _execute_buy(self, trade: dict, market_name: str, slug: str, event_slug: str):
        """Execute a BUY — shared logic for buffered and direct entries."""
        token_id = trade.get("token_id", "")

        if self.reliability.is_wallet_paused(trade.get("wallet", "")):
            print("  Action:  SKIPPED (trader paused - bad performance)")
            self.stats["trades_skipped"] += 1
            tg.notify_trade_skipped(trade, market_name, "Trader pausado por mal rendimiento", slug, event_slug)
            return

        if self.dry_run:
            print("  Action:  SKIPPED (dry run)")
            self.stats["trades_skipped"] += 1
            skip_num = tg.get_skip_counter() + 1
            tg.notify_trade_skipped(trade, market_name, "Modo dry-run activo", slug, event_slug)
            self.skipped_trades.append({
                "skip_number": skip_num,
                "trade": trade,
                "market_name": market_name,
                "slug": slug,
                "event_slug": event_slug,
                "entry_price": trade.get("price", 0),
                "token_id": token_id,
                "timestamp": time.time(),
            })
            return

        if self.positions.has_position(token_id):
            print("  Action:  SKIPPED (already have this position)")
            self.stats["trades_skipped"] += 1
            tg.notify_trade_skipped(trade, market_name, "Ya tenemos posicion en este mercado", slug, event_slug)
            return

        result = self.trader.execute_copy_trade(trade)
        if result:
            self.stats["trades_copied"] += 1
            price = trade.get("price", 0)
            our_size = self.trader._calculate_size(trade.get("size", 0), price)
            print(f"  Action:  COPIED -> {result}")
            tg.notify_trade_copied(
                trade, market_name, our_size, price,
                result if isinstance(result, dict) else {"id": str(result)},
                slug, event_slug,
            )
            self.positions.add_position(
                token_id=token_id, side="BUY", size=our_size,
                entry_price=price, market_name=market_name,
                slug=slug, event_slug=event_slug,
                source_wallet=trade.get("wallet", ""),
            )
            self.reliability.record_trade(token_id, "BUY", price, trade.get("wallet", ""))
        else:
            self.stats["trades_skipped"] += 1
            skip_num = tg.get_skip_counter() + 1
            print("  Action:  SKIPPED (failed or filtered)")
            tg.notify_trade_skipped(trade, market_name, "Orden fallida o filtrada por slippage", slug, event_slug)
            self.skipped_trades.append({
                "skip_number": skip_num,
                "trade": trade,
                "market_name": market_name,
                "slug": slug,
                "event_slug": event_slug,
                "entry_price": trade.get("price", 0),
                "token_id": token_id,
                "timestamp": time.time(),
            })

    def _handle_exit(self, trade: dict, market_name: str, slug: str, event_slug: str):
        """Trader is selling — copy the exit."""
        token_id = trade.get("token_id", "")
        exit_price = trade.get("price", 0)

        print(f"  EXIT DETECTED — trader is selling")

        if self.dry_run:
            print("  Action:  EXIT SKIPPED (dry run)")
            pos = self.positions.close_position(token_id, exit_price, "trader_exit_dry")
            if pos:
                tg.notify_position_closed(pos, exit_price, "Trader vendio (dry-run, no ejecutado)", slug, event_slug)
            return

        # Find our position to know the size
        open_pos = self.positions.get_open_positions()
        our_pos = next((p for p in open_pos if p["token_id"] == token_id), None)
        if not our_pos:
            return

        result = self.trader.execute_sell(token_id, our_pos["size"])
        if result:
            self.stats["exits_copied"] += 1
            actual_price = result.get("price", exit_price)
            closed = self.positions.close_position(token_id, actual_price, "trader_exit")
            if closed:
                print(f"  Action:  EXIT COPIED — PnL: ${closed.get('pnl', 0):.2f}")
                tg.notify_position_closed(closed, actual_price, "Trader vendio — copiamos salida", slug, event_slug)
        else:
            print("  Action:  EXIT FAILED")
            tg.notify_error(f"No se pudo copiar la salida en {market_name}")

    def _check_market_resolutions(self):
        """
        Detect positions where the market has resolved (price went to ~0 or ~1).
        These won't generate a SELL event from the trader, so we handle them here.
        """
        import requests as _req
        for pos in self.positions.get_open_positions():
            token_id = pos.get("token_id")
            if not token_id:
                continue
            try:
                resp = _req.get(
                    f"{config.CLOB_API_URL}/midpoint",
                    params={"token_id": token_id},
                    timeout=10,
                )
                resp.raise_for_status()
                current_price = float(resp.json().get("mid", 0))
            except Exception:
                continue

            if current_price <= 0:
                continue

            market_name = pos.get("market_name", "Unknown")

            # Market resolved YES (we win)
            if current_price >= 0.95:
                closed = self.positions.close_position(token_id, current_price, "market_resolved_yes")
                if closed:
                    print(f"\n[resolved] {market_name} — resolved YES, PnL: ${closed.get('pnl', 0):.2f}")
                    tg.notify_position_closed(
                        closed, current_price,
                        "Mercado resuelto a YES (ganamos)",
                        pos.get("slug", ""), pos.get("event_slug", ""),
                    )

            # Market resolved NO (we lose)
            elif current_price <= 0.05:
                closed = self.positions.close_position(token_id, current_price, "market_resolved_no")
                if closed:
                    print(f"\n[resolved] {market_name} — resolved NO, PnL: ${closed.get('pnl', 0):.2f}")
                    tg.notify_position_closed(
                        closed, current_price,
                        "Mercado resuelto a NO (perdimos)",
                        pos.get("slug", ""), pos.get("event_slug", ""),
                    )

    def _check_stop_losses(self):
        """Periodically check positions for stop-loss triggers."""
        now = time.time()
        if now - self.last_sl_check < STOP_LOSS_CHECK_INTERVAL:
            return
        self.last_sl_check = now

        if self.dry_run:
            return

        triggered = self.positions.check_stop_losses()
        for item in triggered:
            pos = item["position"]
            current_price = item["current_price"]
            loss_pct = item["loss_pct"]
            token_id = pos["token_id"]

            print(f"\n[STOP-LOSS] {pos['market_name']} — loss: {loss_pct:.0%}")

            result = self.trader.execute_sell(token_id, pos["size"])
            if result:
                self.stats["stop_losses"] += 1
                actual_price = result.get("price", current_price)
                closed = self.positions.close_position(token_id, actual_price, "stop_loss")
                if closed:
                    tg.notify_position_closed(
                        closed, actual_price,
                        f"Stop-loss activado ({loss_pct:.0%} perdida)",
                        pos.get("slug", ""), pos.get("event_slug", ""),
                    )
            else:
                tg.notify_error(f"Stop-loss falló en {pos['market_name']}")

    def _check_skipped_outcomes(self):
        """Check current prices for skipped trades and report outcomes."""
        if not self.skipped_trades:
            return

        still_pending = []
        for skipped in self.skipped_trades:
            if time.time() - skipped["timestamp"] < 600:
                still_pending.append(skipped)
                continue

            token_id = skipped.get("token_id")
            if not token_id:
                continue

            try:
                import requests
                resp = requests.get(
                    f"{config.CLOB_API_URL}/midpoint",
                    params={"token_id": token_id},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                current_price = float(data.get("mid", 0))

                if current_price > 0:
                    tg.notify_skipped_outcome(
                        skipped["skip_number"],
                        skipped["trade"],
                        skipped["market_name"],
                        skipped["entry_price"],
                        current_price,
                        skipped.get("slug"),
                        skipped.get("event_slug"),
                    )
                    continue
            except Exception as e:
                print(f"[outcome] Error checking {token_id}: {e}")

            still_pending.append(skipped)

        self.skipped_trades = still_pending

    def _send_periodic_summary(self):
        """Send a periodic summary with portfolio status to Telegram."""
        now = time.time()
        if now - self.last_summary < SUMMARY_INTERVAL:
            return

        self.last_summary = now

        portfolio = self.positions.get_portfolio_summary()
        self.stats["total_pnl"] = portfolio["total_pnl"]
        tg.notify_pnl_update(self.stats, portfolio["positions"])

    def run(self):
        """Main bot loop."""
        self._print_header()
        tg.notify_bot_started(wallet_manager.get_addresses(), self.dry_run)

        if not self.dry_run:
            balance = self.trader.get_balance()
            if balance:
                print(f"[balance] {balance}\n")

        print("[init] Fetching initial wallet state (skipping existing trades)...")
        self.monitor.get_new_trades()
        print("[init] Baseline set. Watching for new trades...\n")

        self.running = True
        self.last_summary = time.time()
        self.last_sl_check = time.time()
        self.commands.start()

        def shutdown(sig, frame):
            print(f"\n\nShutting down...")
            self.running = False
            self.commands.stop()

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        while self.running:
            try:
                new_trades = self.monitor.get_new_trades()
                for trade in new_trades:
                    self._handle_trade(trade)

                if not new_trades:
                    sys.stdout.write(".")
                    sys.stdout.flush()

                self._flush_trade_buffers()
                self._check_stop_losses()
                self._check_market_resolutions()
                self._check_skipped_outcomes()
                self._send_periodic_summary()
                self.reliability.check_reliability()

            except Exception as e:
                print(f"\n[error] {e}")
                tg.notify_error(str(e))

            time.sleep(config.POLL_INTERVAL)

        tg.notify_shutdown(self.stats)
        print(f"\nSession stats: {self.stats}")


def show_status():
    """Show current positions and PnL for all target wallets."""
    addresses = wallet_manager.get_addresses() or config.TARGET_WALLETS
    monitor = WalletMonitor(addresses)

    print("=" * 60)
    print("  Target Wallet Status")
    print("=" * 60)

    for wallet in addresses:
        pnl = monitor.get_wallet_pnl(wallet)
        nick = wallet_manager.get_nickname(wallet)
        print(f"\n  Wallet: {nick}")
        print(f"  Positions:      {pnl['positions']}")
        print(f"  Total cost:     ${pnl['total_cost']}")
        print(f"  Current value:  ${pnl['total_value']}")
        print(f"  Unrealized PnL: ${pnl['unrealized_pnl']}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Polymarket Copy-Trading Bot")
    parser.add_argument("--live", action="store_true", help="Run in live mode (real trades)")
    parser.add_argument("--status", action="store_true", help="Show target wallet PnL and exit")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    bot = CopyTradingBot(dry_run=not args.live)
    bot.run()


if __name__ == "__main__":
    main()
