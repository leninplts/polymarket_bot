"""Telegram command handler — lets you control the bot from Telegram."""

import threading
import requests
import config


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
                    {"command": "dryrun", "description": "Cambiar a modo DRY RUN (solo observar)"},
                    {"command": "pause", "description": "Pausar el bot"},
                    {"command": "resume", "description": "Reanudar el bot"},
                    {"command": "wallets", "description": "Ver wallets que estamos copiando"},
                    {"command": "pnl", "description": "Ver PnL del trader que copiamos"},
                    {"command": "stop", "description": "Detener el bot completamente"},
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

                    # Only respond to our chat
                    if chat_id != str(config.TELEGRAM_CHAT_ID):
                        continue

                    self._handle_command(text)
            except Exception:
                import time
                time.sleep(5)

    def _handle_command(self, text: str):
        cmd = text.strip().lower().split("@")[0]  # Remove @botname suffix

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
        elif cmd == "/pnl":
            self._cmd_pnl()
        elif cmd == "/stop":
            self._cmd_stop()
        elif cmd == "/start":
            self._reply(
                "🤖 <b>Polymarket Copy-Trading Bot</b>\n\n"
                "Comandos disponibles:\n"
                "/status — Estado del bot\n"
                "/live — Cambiar a modo LIVE\n"
                "/dryrun — Cambiar a modo DRY RUN\n"
                "/pause — Pausar\n"
                "/resume — Reanudar\n"
                "/wallets — Ver wallets\n"
                "/pnl — Ver PnL del trader\n"
                "/stop — Detener el bot"
            )

    def _cmd_status(self):
        mode = "🔬 DRY RUN" if self.bot.dry_run else "⚡ LIVE"
        state = "⏸ PAUSADO" if not self.bot.running else "▶️ ACTIVO"
        s = self.bot.stats
        self._reply(
            f"{'━' * 28}\n"
            f"📊 <b>ESTADO DEL BOT</b>\n"
            f"{'━' * 28}\n\n"
            f"Modo: {mode}\n"
            f"Estado: {state}\n\n"
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
            "⚠️ A partir de ahora los trades se ejecutaran con dinero real.\n"
            f"Size: ${config.FIXED_AMOUNT} por trade"
        )

    def _cmd_dryrun(self):
        if self.bot.dry_run:
            self._reply("🔬 Ya estás en modo <b>DRY RUN</b>")
            return

        self.bot.dry_run = True
        self._reply("🔬 <b>MODO DRY RUN ACTIVADO</b>\n\nSolo observando, no se ejecutan trades.")

    def _cmd_pause(self):
        if not self.bot.running:
            self._reply("⏸ El bot ya está pausado")
            return
        self.bot.running = False
        self._reply("⏸ <b>BOT PAUSADO</b>\n\nUsa /resume para reanudar.")

    def _cmd_resume(self):
        if self.bot.running:
            self._reply("▶️ El bot ya está corriendo")
            return
        self.bot.running = True
        self._reply("▶️ <b>BOT REANUDADO</b>\n\nMonitoreando trades de nuevo.")

    def _cmd_wallets(self):
        lines = []
        for w in config.TARGET_WALLETS:
            lines.append(f'  └ <a href="https://polymarket.com/profile/{w}">{w[:10]}...{w[-6:]}</a>')
        self._reply(
            f"{'━' * 28}\n"
            f"👁 <b>WALLETS MONITOREADAS</b>\n"
            f"{'━' * 28}\n\n"
            + "\n".join(lines)
        )

    def _cmd_pnl(self):
        from wallet_monitor import WalletMonitor
        monitor = WalletMonitor(config.TARGET_WALLETS)

        lines = []
        for w in config.TARGET_WALLETS:
            pnl = monitor.get_wallet_pnl(w)
            emoji = "📈" if pnl["unrealized_pnl"] >= 0 else "📉"
            short = f'{w[:10]}...{w[-6:]}'
            lines.append(
                f'<a href="https://polymarket.com/profile/{w}">{short}</a>\n'
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

    def _cmd_stop(self):
        self._reply("🛑 <b>DETENIENDO BOT...</b>")
        self.bot.running = False
        self.running = False
