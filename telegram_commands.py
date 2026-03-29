"""Telegram command handler — lets you control the bot from Telegram."""

import threading
import requests
import config
import wallet_manager


class TelegramCommands:
    def __init__(self, bot_ref):
        """bot_ref is the CopyTradingBot instance."""
        self.bot = bot_ref
        self.last_update_id = 0
        self.running = False
        self._thread = None

    def start(self):
        """Start polling for Telegram commands in a background thread."""
        if not config.TELEGRAM_BOT_TOKEN:
            return
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._set_bot_commands()
        print("[telegram] Command listener started")

    def stop(self):
        self.running = False

    def _set_bot_commands(self):
        """Register the command menu in Telegram."""
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setMyCommands",
                json={"commands": [
                    {"command": "status", "description": "Ver estado del bot y stats"},
                    {"command": "live", "description": "Cambiar a modo LIVE (trades reales)"},
                    {"command": "dryrun", "description": "Cambiar a modo DRY RUN"},
                    {"command": "pause", "description": "Pausar el bot"},
                    {"command": "resume", "description": "Reanudar el bot"},
                    {"command": "wallets", "description": "Ver wallets que copiamos"},
                    {"command": "addwallet", "description": "Agregar wallet: /addwallet 0x... nombre"},
                    {"command": "removewallet", "description": "Quitar wallet: /removewallet 0x..."},
                    {"command": "pnl", "description": "Ver PnL de traders"},
                    {"command": "portfolio", "description": "Ver nuestras posiciones abiertas"},
                    {"command": "scan", "description": "Buscar nuevas wallets rentables"},
                    {"command": "stop", "description": "Detener el bot"},
                ]},
                timeout=10,
            )
        except Exception:
            pass

    def _reply(self, text: str):
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception:
            pass

    def _poll_loop(self):
        while self.running:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": self.last_update_id + 1, "timeout": 10},
                    timeout=15,
                )
                data = resp.json()
                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id != str(config.TELEGRAM_CHAT_ID):
                        continue

                    self._handle_command(text)
            except Exception:
                import time
                time.sleep(5)

    def _handle_command(self, text: str):
        parts = text.strip().split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        if cmd == "/status":
            self._cmd_status()
        elif cmd == "/live":
            self._cmd_live()
        elif cmd == "/dryrun":
            self._cmd_dryrun()
        elif cmd == "/pause":
            self._cmd_pause()
        elif cmd == "/resume":
            self._cmd_resume()
        elif cmd == "/wallets":
            self._cmd_wallets()
        elif cmd == "/addwallet":
            self._cmd_add_wallet(args)
        elif cmd == "/removewallet":
            self._cmd_remove_wallet(args)
        elif cmd == "/pnl":
            self._cmd_pnl()
        elif cmd == "/portfolio":
            self._cmd_portfolio()
        elif cmd == "/scan":
            self._cmd_scan()
        elif cmd == "/stop":
            self._cmd_stop()
        elif cmd == "/start":
            self._reply(
                "🤖 <b>Polymarket Copy-Trading Bot</b>\n\n"
                "<b>Control:</b>\n"
                "/status — Estado del bot\n"
                "/live — Modo LIVE\n"
                "/dryrun — Modo DRY RUN\n"
                "/pause — Pausar\n"
                "/resume — Reanudar\n"
                "/stop — Detener\n\n"
                "<b>Wallets:</b>\n"
                "/wallets — Ver wallets activas\n"
                "/addwallet 0x... nick — Agregar\n"
                "/removewallet 0x... — Quitar\n"
                "/pnl — Ver PnL\n"
                "/portfolio — Nuestras posiciones\n"
                "/scan — Buscar wallets rentables"
            )

    # ─── Bot control ─────────────────────────────────────

    def _cmd_status(self):
        mode = "🔬 DRY RUN" if self.bot.dry_run else "⚡ LIVE"
        state = "⏸ PAUSADO" if not self.bot.running else "▶️ ACTIVO"
        s = self.bot.stats
        paused_wallets = len(self.bot.reliability.paused_wallets)

        self._reply(
            f"{'━' * 28}\n"
            f"📊 <b>ESTADO DEL BOT</b>\n"
            f"{'━' * 28}\n\n"
            f"Modo: {mode}\n"
            f"Estado: {state}\n"
            f"Wallets activas: {len(wallet_manager.get_all())}\n"
            f"Wallets pausadas: {paused_wallets}\n\n"
            f"Trades detectados: <b>{s.get('trades_detected', 0)}</b>\n"
            f"Trades copiados: <b>{s.get('trades_copied', 0)}</b>\n"
            f"Trades saltados: <b>{s.get('trades_skipped', 0)}</b>"
        )

    def _cmd_live(self):
        if not self.bot.dry_run:
            self._reply("⚡ Ya estás en modo <b>LIVE</b>")
            return

        if self.bot.trader is None:
            try:
                from trader import Trader
                self.bot.trader = Trader()
            except Exception as e:
                self._reply(f"🚨 Error al inicializar trader: <code>{e}</code>")
                return

        self.bot.dry_run = False
        self._reply(
            "⚡ <b>MODO LIVE ACTIVADO</b>\n\n"
            "⚠️ Trades reales a partir de ahora.\n"
            f"Max size: ${config.FIXED_AMOUNT} (dinamico por probabilidad)"
        )

    def _cmd_dryrun(self):
        if self.bot.dry_run:
            self._reply("🔬 Ya estás en modo <b>DRY RUN</b>")
            return
        self.bot.dry_run = True
        self._reply("🔬 <b>MODO DRY RUN ACTIVADO</b>\n\nSolo observando.")

    def _cmd_pause(self):
        if not self.bot.running:
            self._reply("⏸ Ya está pausado")
            return
        self.bot.running = False
        self._reply("⏸ <b>BOT PAUSADO</b>\n\n/resume para reanudar.")

    def _cmd_resume(self):
        if self.bot.running:
            self._reply("▶️ Ya está corriendo")
            return
        self.bot.running = True
        self._reply("▶️ <b>BOT REANUDADO</b>")

    def _cmd_stop(self):
        self._reply("🛑 <b>DETENIENDO BOT...</b>")
        self.bot.running = False
        self.running = False

    # ─── Wallet management ───────────────────────────────

    def _cmd_wallets(self):
        wallets = wallet_manager.get_all()
        if not wallets:
            self._reply("No hay wallets configuradas. Usa /addwallet o /scan")
            return

        lines = []
        for w in wallets:
            addr = w["address"]
            nick = w.get("nickname") or f"{addr[:10]}...{addr[-6:]}"
            paused = " ⏸" if self.bot.reliability.is_wallet_paused(addr) else ""
            lines.append(
                f'  └ <b>{nick}</b>{paused}\n'
                f'      <a href="https://polymarket.com/profile/{addr}">{addr[:10]}...{addr[-6:]}</a>'
            )

        self._reply(
            f"{'━' * 28}\n"
            f"👁 <b>WALLETS ({len(wallets)})</b>\n"
            f"{'━' * 28}\n\n"
            + "\n\n".join(lines)
        )

    def _cmd_add_wallet(self, args: list[str]):
        if not args:
            self._reply(
                "Uso: /addwallet <code>0x...</code> nombre\n\n"
                "Ejemplo:\n"
                "<code>/addwallet 0x3b5c629f114098b0dee345fb78b7a3a013c7126e SMCAOMCRL</code>"
            )
            return

        address = args[0]
        nickname = " ".join(args[1:]) if len(args) > 1 else ""

        if not address.startswith("0x") or len(address) < 20:
            self._reply("⚠️ Direccion invalida. Debe empezar con 0x")
            return

        # Fetch nickname from API if not provided
        if not nickname:
            from find_wallets import _get_nickname
            nickname = _get_nickname(address)

        if wallet_manager.add_wallet(address, nickname):
            # Update the bot's monitor with the new wallet list
            self.bot.monitor.wallets = wallet_manager.get_addresses()

            display_name = nickname or f"{address[:10]}...{address[-6:]}"
            self._reply(
                f"{'━' * 28}\n"
                f"✅ <b>WALLET AGREGADA</b>\n"
                f"{'━' * 28}\n\n"
                f"👤 <b>{display_name}</b>\n"
                f"<a href=\"https://polymarket.com/profile/{address}\">{address[:10]}...{address[-6:]}</a>\n\n"
                f"Total wallets: {len(wallet_manager.get_all())}"
            )
        else:
            self._reply("⚠️ Esta wallet ya está en la lista.")

    def _cmd_remove_wallet(self, args: list[str]):
        if not args:
            self._reply("Uso: /removewallet <code>0x...</code>")
            return

        address = args[0]
        nickname = wallet_manager.get_nickname(address)

        if wallet_manager.remove_wallet(address):
            self.bot.monitor.wallets = wallet_manager.get_addresses()
            self._reply(
                f"{'━' * 28}\n"
                f"🗑 <b>WALLET ELIMINADA</b>\n"
                f"{'━' * 28}\n\n"
                f"👤 <b>{nickname}</b>\n\n"
                f"Total wallets: {len(wallet_manager.get_all())}"
            )
        else:
            self._reply("⚠️ Wallet no encontrada.")

    def _cmd_pnl(self):
        from wallet_monitor import WalletMonitor
        wallets = wallet_manager.get_all()

        if not wallets:
            self._reply("No hay wallets configuradas.")
            return

        addresses = [w["address"] for w in wallets]
        monitor = WalletMonitor(addresses)

        lines = []
        for w in wallets:
            addr = w["address"]
            nick = w.get("nickname") or f"{addr[:10]}...{addr[-6:]}"
            pnl = monitor.get_wallet_pnl(addr)
            emoji = "📈" if pnl["unrealized_pnl"] >= 0 else "📉"
            paused = " ⏸" if self.bot.reliability.is_wallet_paused(addr) else ""

            lines.append(
                f'<b>{nick}</b>{paused}\n'
                f'<a href="https://polymarket.com/profile/{addr}">{addr[:10]}...{addr[-6:]}</a>\n'
                f"    Posiciones: {pnl['positions']}\n"
                f"    Costo: ${pnl['total_cost']:,.2f}\n"
                f"    Valor: ${pnl['total_value']:,.2f}\n"
                f"    {emoji} PnL: <b>${pnl['unrealized_pnl']:,.2f}</b>"
            )

        self._reply(
            f"{'━' * 28}\n"
            f"💰 <b>PNL DE TRADERS</b>\n"
            f"{'━' * 28}\n\n"
            + "\n\n".join(lines)
        )

    def _cmd_portfolio(self):
        summary = self.bot.positions.get_portfolio_summary()

        if summary["open_count"] == 0 and summary["realized_pnl"] == 0:
            self._reply("📭 No hay posiciones abiertas ni cerradas.")
            return

        emoji = "📈" if summary["total_pnl"] >= 0 else "📉"
        text = (
            f"{'━' * 28}\n"
            f"📊 <b>NUESTRO PORTFOLIO</b>\n"
            f"{'━' * 28}\n\n"
            f"Posiciones abiertas: <b>{summary['open_count']}</b>\n"
            f"Invertido: <b>${summary['total_invested']:,.2f}</b>\n"
            f"PnL no realizado: <b>${summary['unrealized_pnl']:,.2f}</b>\n"
            f"PnL realizado: <b>${summary['realized_pnl']:,.2f}</b>\n"
            f"{emoji} PnL total: <b>${summary['total_pnl']:,.2f}</b>\n"
        )

        if summary["positions"]:
            text += "\n<b>Posiciones abiertas:</b>\n"
            for p in summary["positions"]:
                em = "✅" if p["pnl"] >= 0 else "❌"
                market = p["market_name"][:30]
                text += (
                    f"\n  {em} {market}\n"
                    f"      Entrada: {p['entry_price']} → Actual: {p['current_price']}\n"
                    f"      PnL: <b>${p['pnl']:,.2f}</b> ({p['pnl_pct']:+.1f}%)\n"
                )

        self._reply(text)

    # ─── Scanner ─────────────────────────────────────────

    def _cmd_scan(self):
        self._reply("🔍 <b>Escaneando mercados...</b>\n30 mercados × 500 trades c/u\nEsto puede tardar 3-5 minutos.")

        # Run in a thread to not block command processing
        t = threading.Thread(target=self._run_scan, daemon=True)
        t.start()

    def _run_scan(self):
        try:
            from find_wallets import get_top_markets, find_profitable_wallets, format_wallet_summary

            markets = get_top_markets(30)
            results = find_profitable_wallets(markets, quiet=True)

            if not results:
                self._reply(
                    "🔍 <b>Scan completado</b>\n\n"
                    "No se encontraron wallets que cumplan:\n"
                    "  PnL>$500 | WR>55% | 10+pos | Activo<7d | Cuenta>30d"
                )
                return

            # Filter out wallets we already have
            current = set(wallet_manager.get_addresses())
            new_results = [r for r in results if r["address"] not in current]

            # Send header
            self._reply(
                f"{'━' * 28}\n"
                f"🔍 <b>SCAN COMPLETADO</b>\n"
                f"{'━' * 28}\n\n"
                f"Total encontradas: <b>{len(results)}</b>\n"
                f"Nuevas (no agregadas): <b>{len(new_results)}</b>\n"
                f"Ya monitoreadas: <b>{len(results) - len(new_results)}</b>"
            )

            # Send wallets in batches of 3 to avoid message size limits
            import time as _time
            for i in range(0, min(len(new_results), 10), 3):
                batch = new_results[i:i + 3]
                text = ""
                for j, w in enumerate(batch, i + 1):
                    text += f"<b>#{j}</b> " + format_wallet_summary(w) + "\n\n"
                self._reply(text)
                _time.sleep(0.5)

            if new_results:
                top = new_results[0]
                name = top.get("nickname") or "trader"
                self._reply(
                    f"💡 Para agregar la mejor:\n"
                    f"<code>/addwallet {top['address']} {name}</code>"
                )

        except Exception as e:
            self._reply(f"🚨 Error en scan: <code>{e}</code>")
