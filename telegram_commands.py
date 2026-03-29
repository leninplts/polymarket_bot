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
                    {"command": "addwallet", "description": "Agregar: /addwallet 0x... o /addwallet nombre"},
                    {"command": "removewallet", "description": "Quitar: /removewallet 0x... o /removewallet nombre"},
                    {"command": "pausewallet", "description": "Pausar wallet: /pausewallet nombre"},
                    {"command": "resumewallet", "description": "Reanudar wallet: /resumewallet nombre"},
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
        elif cmd == "/pausewallet":
            self._cmd_pause_wallet(args)
        elif cmd == "/resumewallet":
            self._cmd_resume_wallet(args)
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
                "/addwallet nombre — Agregar\n"
                "/removewallet nombre — Quitar\n"
                "/pausewallet nombre — Pausar wallet\n"
                "/resumewallet nombre — Reanudar wallet\n"
                "/pnl — Ver PnL\n"
                "/portfolio — Nuestras posiciones\n"
                "/scan — Buscar wallets rentables"
            )

    # ─── Bot control ─────────────────────────────────────

    def _cmd_status(self):
        mode = "🔬 DRY RUN" if self.bot.dry_run else "⚡ LIVE"
        state = "⏸ PAUSADO" if not self.bot.running else "▶️ ACTIVO"
        s = self.bot.stats
        all_wallets = wallet_manager.get_all()
        manually_paused = sum(1 for w in all_wallets if wallet_manager.is_paused(w["address"]))
        auto_paused = len(self.bot.reliability.paused_wallets)
        active = len(all_wallets) - manually_paused

        self._reply(
            f"{'━' * 28}\n"
            f"📊 <b>ESTADO DEL BOT</b>\n"
            f"{'━' * 28}\n\n"
            f"Modo: {mode}\n"
            f"Estado: {state}\n"
            f"Wallets activas: <b>{active}</b> / {len(all_wallets)}\n"
            f"Pausadas manualmente: {manually_paused}\n"
            f"Pausadas (rendimiento): {auto_paused}\n\n"
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
            manually_paused = wallet_manager.is_paused(addr)
            auto_paused = self.bot.reliability.is_wallet_paused(addr)
            if manually_paused:
                status = " ⏸ <i>pausada manualmente</i>"
            elif auto_paused:
                status = " ⚠️ <i>pausada (bajo rendimiento)</i>"
            else:
                status = " ✅"
            lines.append(
                f'  └ <b>{nick}</b>{status}\n'
                f'      <a href="https://polymarket.com/profile/{addr}">{addr[:10]}...{addr[-6:]}</a>'
            )

        self._reply(
            f"{'━' * 28}\n"
            f"👁 <b>WALLETS ({len(wallets)})</b>\n"
            f"{'━' * 28}\n\n"
            + "\n\n".join(lines)
        )

    def _resolve_wallet_by_name(self, name: str) -> tuple[str, str]:
        """
        Given a nickname, search the Polymarket leaderboard and return (address, nickname).
        Returns ("", "") if not found.
        """
        try:
            from find_wallets import get_leaderboard_wallets
            lb = get_leaderboard_wallets()
            name_lower = name.lower()
            for w in lb:
                if w.get("nickname", "").lower() == name_lower:
                    return w["address"], w["nickname"]
            # Partial match fallback
            for w in lb:
                if name_lower in w.get("nickname", "").lower():
                    return w["address"], w["nickname"]
        except Exception:
            pass
        return "", ""

    def _cmd_add_wallet(self, args: list[str]):
        if not args:
            self._reply(
                "Uso: /addwallet <code>0x...</code> [nombre]\n"
                "  o: /addwallet <b>nombre</b> (busca en leaderboard)\n\n"
                "Ejemplos:\n"
                "<code>/addwallet 0x3b5c629f...  SMCAOMCRL</code>\n"
                "<code>/addwallet RN1</code>"
            )
            return

        first_arg = args[0]

        # --- By name: search leaderboard ---
        if not first_arg.startswith("0x"):
            name_query = " ".join(args)
            self._reply(f"🔍 Buscando <b>{name_query}</b> en el leaderboard...")
            address, nickname = self._resolve_wallet_by_name(name_query)
            if not address:
                self._reply(f"⚠️ No se encontro <b>{name_query}</b> en el leaderboard de Polymarket.")
                return
        else:
            address = first_arg
            nickname = " ".join(args[1:]) if len(args) > 1 else ""
            if len(address) < 20:
                self._reply("⚠️ Direccion invalida.")
                return
            # Auto-fetch nickname from activity if not provided
            if not nickname:
                try:
                    import requests, config
                    resp = requests.get(
                        f"{config.DATA_API_URL}/activity",
                        params={"user": address, "limit": 1},
                        timeout=10,
                    )
                    data = resp.json()
                    if data:
                        nickname = data[0].get("name") or data[0].get("pseudonym") or ""
                except Exception:
                    pass

        if wallet_manager.add_wallet(address, nickname):
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
            display_name = nickname or f"{address[:10]}...{address[-6:]}"
            self._reply(f"⚠️ <b>{display_name}</b> ya esta en la lista.")

    def _cmd_remove_wallet(self, args: list[str]):
        if not args:
            self._reply(
                "Uso: /removewallet <code>0x...</code>\n"
                "  o: /removewallet <b>nombre</b>"
            )
            return

        first_arg = args[0]

        # --- By name: search monitored wallets ---
        if not first_arg.startswith("0x"):
            name_query = " ".join(args).lower()
            wallets = wallet_manager.get_all()
            match = None
            # Exact match first
            for w in wallets:
                if w.get("nickname", "").lower() == name_query:
                    match = w
                    break
            # Partial match fallback
            if not match:
                for w in wallets:
                    if name_query in w.get("nickname", "").lower():
                        match = w
                        break
            if not match:
                self._reply(f"⚠️ No se encontro <b>{' '.join(args)}</b> en las wallets monitoreadas.")
                return
            address = match["address"]
            nickname = match.get("nickname") or f"{address[:10]}...{address[-6:]}"
        else:
            address = first_arg
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
            self._reply(f"⚠️ Wallet no encontrada.")

    def _resolve_monitored_wallet(self, args: list[str]) -> tuple[str, str]:
        """Resolve address+nickname from args (supports name or 0x address)."""
        if not args:
            return "", ""
        first_arg = args[0]
        if first_arg.startswith("0x"):
            return first_arg.lower(), wallet_manager.get_nickname(first_arg)
        # Search by name
        name_query = " ".join(args).lower()
        wallets = wallet_manager.get_all()
        for w in wallets:
            if w.get("nickname", "").lower() == name_query:
                return w["address"], w.get("nickname") or w["address"][:12]
        for w in wallets:
            if name_query in w.get("nickname", "").lower():
                return w["address"], w.get("nickname") or w["address"][:12]
        return "", ""

    def _cmd_pause_wallet(self, args: list[str]):
        if not args:
            self._reply(
                "Uso: /pausewallet <b>nombre</b> o <b>0x...</b>\n\n"
                "Ejemplo: <code>/pausewallet RN1</code>"
            )
            return

        address, nickname = self._resolve_monitored_wallet(args)
        if not address:
            self._reply(f"⚠️ No se encontro <b>{' '.join(args)}</b> en las wallets monitoreadas.")
            return

        result = wallet_manager.pause_wallet(address)
        if result:
            self._reply(
                f"{'━' * 28}\n"
                f"⏸ <b>WALLET PAUSADA</b>\n"
                f"{'━' * 28}\n\n"
                f"👤 <b>{nickname}</b>\n"
                f"<code>{address}</code>\n\n"
                f"El bot dejara de copiar sus trades.\n"
                f"Usa /resumewallet {nickname} para reanudar."
            )
        else:
            self._reply(f"⚠️ <b>{nickname}</b> ya estaba pausada o no se encontro.")

    def _cmd_resume_wallet(self, args: list[str]):
        if not args:
            self._reply(
                "Uso: /resumewallet <b>nombre</b> o <b>0x...</b>\n\n"
                "Ejemplo: <code>/resumewallet RN1</code>"
            )
            return

        address, nickname = self._resolve_monitored_wallet(args)
        if not address:
            self._reply(f"⚠️ No se encontro <b>{' '.join(args)}</b> en las wallets monitoreadas.")
            return

        result = wallet_manager.resume_wallet(address)
        if result:
            self._reply(
                f"{'━' * 28}\n"
                f"▶️ <b>WALLET REANUDADA</b>\n"
                f"{'━' * 28}\n\n"
                f"👤 <b>{nickname}</b>\n"
                f"<code>{address}</code>\n\n"
                f"El bot volvera a copiar sus trades."
            )
        else:
            self._reply(f"⚠️ <b>{nickname}</b> no estaba pausada o no se encontro.")

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
        self._reply("🔍 <b>Escaneando leaderboard de Polymarket...</b>\nEsto tarda ~20 segundos.")

        # Run in a thread to not block command processing
        t = threading.Thread(target=self._run_scan, daemon=True)
        t.start()

    def _run_scan(self):
        import time as _time
        try:
            from find_wallets import (
                get_leaderboard_wallets, scan_wallet,
                format_wallet_summary, MAX_INACTIVE_DAYS, MIN_ACCOUNT_AGE_DAYS,
                WALLET_WORKERS,
            )
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # --- Fase 1: leaderboard ---
            self._reply("📡 <b>[1/3]</b> Obteniendo leaderboard oficial de Polymarket...")
            lb_wallets = get_leaderboard_wallets(period="all")
            self._reply(f"✅ <b>[1/3]</b> {len(lb_wallets)} wallets en el leaderboard.")

            # --- Fase 2: enriquecer con datos de actividad ---
            self._reply(f"🔬 <b>[2/3]</b> Enriqueciendo {len(lb_wallets)} wallets con datos de actividad...")
            results = []
            done = 0
            total = len(lb_wallets)

            def _enrich(entry):
                return scan_wallet(entry["address"], leaderboard_data=entry)

            with ThreadPoolExecutor(max_workers=WALLET_WORKERS) as ex:
                futures = {ex.submit(_enrich, entry): entry for entry in lb_wallets}
                for fut in as_completed(futures):
                    done += 1
                    stats = fut.result()
                    if stats is None:
                        continue
                    if stats["days_since_last_trade"] > MAX_INACTIVE_DAYS:
                        continue
                    if stats["account_age_days"] > 0 and stats["account_age_days"] < MIN_ACCOUNT_AGE_DAYS:
                        continue
                    results.append(stats)
            results.sort(key=lambda x: x["leaderboard_pnl"], reverse=True)
            self._reply(f"✅ <b>[2/3]</b> {done} wallets procesadas, <b>{len(results)} activas en los ultimos {MAX_INACTIVE_DAYS} dias</b>.")

            # --- Fase 3: enviar resultados ---
            self._reply("📊 <b>[3/3]</b> Preparando resultados...")

            if not results:
                self._reply(
                    "🔍 <b>Scan completado — sin resultados</b>\n\n"
                    f"Ninguna wallet del leaderboard estuvo activa en los ultimos {MAX_INACTIVE_DAYS} dias."
                )
                return

            current = set(wallet_manager.get_addresses())
            new_results = [r for r in results if r["address"] not in current]

            self._reply(
                f"{'━' * 28}\n"
                f"🔍 <b>SCAN COMPLETADO</b>\n"
                f"{'━' * 28}\n\n"
                f"Total encontradas: <b>{len(results)}</b>\n"
                f"Nuevas (no agregadas): <b>{len(new_results)}</b>\n"
                f"Ya monitoreadas: <b>{len(results) - len(new_results)}</b>"
            )

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
            import traceback
            self._reply(f"🚨 <b>Error en scan:</b>\n<code>{e}</code>\n\n<code>{traceback.format_exc()[-500:]}</code>")
