"""
Polymarket Copy-Trading Bot

Monitors profitable wallets and copies their trades on Polymarket.
Starts in DRY RUN by default — use /live from Telegram to activate.

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
import market_cache
import telegram_notifier as tg
from telegram_commands import TelegramCommands
from reliability_tracker import ReliabilityTracker

SUMMARY_INTERVAL = 1800  # 30 minutes


class CopyTradingBot:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        # Initialize wallet manager from config if first run
        wallet_manager.init_from_config(config.TARGET_WALLETS)
        self.monitor = WalletMonitor(wallet_manager.get_addresses())
        self.trader = None if dry_run else Trader()
        self.running = False
        self.stats = {"trades_detected": 0, "trades_copied": 0, "trades_skipped": 0}
        self.skipped_trades = []
        self.last_summary = 0
        self.commands = TelegramCommands(self)
        self.reliability = ReliabilityTracker()

    def _print_header(self):
        mode = "DRY RUN" if self.dry_run else "LIVE"
        wallets = wallet_manager.get_all()
        print("=" * 60)
        print(f"  Polymarket Copy-Trading Bot [{mode}]")
        print(f"  Monitoring {len(wallets)} wallet(s)")
        print(f"  Sizing: dynamic (max ${config.FIXED_AMOUNT} based on probability)")
        print(f"  Max slippage: {config.MAX_SLIPPAGE:.1%}")
        print(f"  Poll interval: {config.POLL_INTERVAL}s")
        print(f"  Summary every: {SUMMARY_INTERVAL // 60} min")
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
        """Process a detected trade."""
        self.stats["trades_detected"] += 1
        wallet_short = f"{trade['wallet'][:10]}...{trade['wallet'][-6:]}"
        market_name, slug, event_slug = self._get_market_info(trade)

        print(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] "
            f"TRADE DETECTED from {wallet_short}"
        )
        print(f"  Market:  {market_name}")
        print(f"  Side:    {trade.get('side', '?')}")
        print(f"  Size:    {trade.get('size', '?')}")
        print(f"  Price:   {trade.get('price', '?')}")
        print(f"  Outcome: {trade.get('outcome', '?')}")

        tg.notify_trade_detected(trade, market_name, slug, event_slug)

        # Check if this wallet is paused due to bad performance
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
                "token_id": trade.get("token_id"),
                "timestamp": time.time(),
            })
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
            # Record for reliability tracking
            self.reliability.record_trade(
                trade.get("token_id", ""), trade.get("side", "BUY"),
                price, trade.get("wallet", ""),
            )
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
                "token_id": trade.get("token_id"),
                "timestamp": time.time(),
            })

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
        """Send a periodic summary to Telegram."""
        now = time.time()
        if now - self.last_summary < SUMMARY_INTERVAL:
            return

        self.last_summary = now
        tg.notify_pnl_update(self.stats)

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
    monitor = WalletMonitor(config.TARGET_WALLETS)

    print("=" * 60)
    print("  Target Wallet Status")
    print("=" * 60)

    for wallet in config.TARGET_WALLETS:
        pnl = monitor.get_wallet_pnl(wallet)
        print(f"\n  Wallet: {wallet[:10]}...{wallet[-6:]}")
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

    if not config.TARGET_WALLETS:
        print("Error: No TARGET_WALLETS configured. Set them in .env")
        sys.exit(1)

    if args.status:
        show_status()
        return

    bot = CopyTradingBot(dry_run=not args.live)
    bot.run()


if __name__ == "__main__":
    main()
