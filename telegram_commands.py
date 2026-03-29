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
            print("[telegram] WARNING: TELEGRAM_BOT_TOKEN no configurado — comandos deshabilitados")
            return
        if not config.TELEGRAM_CHAT_ID:
            print("[telegram] WARNING: TELEGRAM_CHAT_ID no configurado — comandos deshabilitados")
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
        commands = [
            {"command": "status", "description": "Estado del bot"},
            {"command": "dryrun", "description": "/dryrun nombre — Solo observar"},
            {"command": "demo", "description": "/demo nombre — Cuenta demo virtual"},
            {"command": "live", "description": "/live nombre — Trades reales"},
            {"command": "pause", "description": "Pausar el bot"},
            {"command": "resume", "description": "Reanudar el bot"},
            {"command": "wallets", "description": "Ver wallets y sus modos"},
            {"command": "addwallet", "description": "Agregar wallet (entra en dry)"},
            {"command": "removewallet", "description": "Quitar wallet"},
            {"command": "pausewallet", "description": "Pausar wallet: /pausewallet nombre"},
            {"command": "resumewallet", "description": "Reanudar wallet: /resumewallet nombre"},
            {"command": "demobalance", "description": "Ver cuenta demo (balance, PnL)"},
            {"command": "demoreset", "description": "Reiniciar cuenta demo"},
            {"command": "demoexport", "description": "Exportar datos demo (JSON)"},
            {"command": "pnl", "description": "Ver PnL de traders"},
            {"command": "portfolio", "description": "Ver posiciones reales abiertas"},
            {"command": "scan", "description": "Buscar nuevas wallets rentables"},
            {"command": "stop", "description": "Detener el bot"},
        ]
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setMyCommands",
                json={"commands": commands},
                timeout=10,
            )
            resp.raise_for_status()
            print(f"[telegram] {len(commands)} comandos registrados OK")
        except Exception as e:
            print(f"[telegram] ERROR registrando comandos: {e}")

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
            self._cmd_set_mode(args, "live")
        elif cmd == "/demo":
            self._cmd_set_mode(args, "demo")
        elif cmd == "/dryrun":
            self._cmd_set_mode(args, "dry")
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
        elif cmd == "/demobalance":
            self._cmd_demo_balance()
        elif cmd == "/demoreset":
            self._cmd_demo_reset(args)
        elif cmd == "/demoexport":
            self._cmd_demo_export()
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
                "/pause — Pausar bot\n"
                "/resume — Reanudar bot\n"
                "/stop — Detener bot\n\n"
                "<b>Modos por wallet:</b>\n"
                "/dryrun RN1 — Solo observar\n"
                "/demo RN1 — Cuenta demo virtual\n"
                "/live RN1 — Trades reales\n\n"
                "<b>Wallets:</b>\n"
                "/wallets — Ver wallets y sus modos\n"
                "/addwallet nombre — Agregar (entra en dry)\n"
                "/removewallet nombre — Quitar\n"
                "/pausewallet nombre — Pausar wallet\n"
                "/resumewallet nombre — Reanudar wallet\n\n"
                "<b>Demo:</b>\n"
                "/demobalance — Ver cuenta demo\n"
                "/demoexport — Exportar datos demo (JSON)\n"
                "/demoreset — Reiniciar cuenta demo\n\n"
                "<b>Analisis:</b>\n"
                "/pnl — PnL de traders\n"
                "/portfolio — Posiciones reales abiertas\n"
                "/scan — Buscar wallets rentables"
            )

    # ─── Bot control ─────────────────────────────────────

    def _cmd_status(self):
        global_mode = "🔬 OVERRIDE DRY" if self.bot.dry_run else "✅ Normal"
        state = "⏸ PAUSADO" if not self.bot.running else "▶️ ACTIVO"
        s = self.bot.stats
        all_wallets = wallet_manager.get_all()
        manually_paused = sum(1 for w in all_wallets if wallet_manager.is_paused(w["address"]))
        auto_paused = len(self.bot.reliability.paused_wallets)
        n_dry  = sum(1 for w in all_wallets if wallet_manager.get_mode(w["address"]) == "dry")
        n_demo = sum(1 for w in all_wallets if wallet_manager.get_mode(w["address"]) == "demo")
        n_live = sum(1 for w in all_wallets if wallet_manager.get_mode(w["address"]) == "live")

        demo_s = self.bot.demo.get_summary()
        demo_pnl = demo_s["total_pnl"]
        demo_str = f"+${demo_pnl:,.2f}" if demo_pnl >= 0 else f"-${abs(demo_pnl):,.2f}"

        self._reply(
            f"{'━' * 28}\n"
            f"📊 <b>ESTADO DEL BOT</b>\n"
            f"{'━' * 28}\n\n"
            f"Override global: {global_mode}\n"
            f"Estado: {state}\n\n"
            f"<b>Wallets ({len(all_wallets)}):</b>\n"
            f"  🔬 Dry:  {n_dry}\n"
            f"  🎮 Demo: {n_demo}\n"
            f"  ⚡ Live: {n_live}\n"
            f"  ⏸ Pausadas: {manually_paused + auto_paused}\n\n"
            f"<b>Cuenta demo:</b>\n"
            f"  Balance: ${demo_s['balance']:,.2f} | PnL: {demo_str}\n\n"
            f"<b>Trades:</b>\n"
            f"  Detectados: <b>{s.get('trades_detected', 0)}</b>\n"
            f"  Copiados:   <b>{s.get('trades_copied', 0)}</b>\n"
            f"  Saltados:   <b>{s.get('trades_skipped', 0)}</b>"
        )

    def _cmd_set_mode(self, args: list[str], mode: str):
        """
        Set mode for a specific wallet or for the global bot override.
        /live RN1    -> RN1 goes live
        /demo RN1    -> RN1 goes demo
        /dryrun RN1  -> RN1 goes dry
        /live        -> (no args) global live override (legacy)
        /dryrun      -> (no args) global dry override
        """
        mode_labels = {
            "dry":  ("🔬", "DRY RUN",  "Solo observando, sin ejecutar nada."),
            "demo": ("🎮", "DEMO",     f"Cuenta virtual de ${config.DEMO_BALANCE:.0f}."),
            "live": ("⚡", "LIVE",     f"Trades reales. Max ${config.FIXED_AMOUNT}/orden."),
        }
        emoji, label, desc = mode_labels[mode]

        # No args = global override (legacy behavior)
        if not args:
            if mode == "live":
                if not self.bot.dry_run:
                    self._reply(f"{emoji} Ya estas en modo global <b>{label}</b>")
                    return
                if self.bot.trader is None:
                    try:
                        from trader import Trader
                        self.bot.trader = Trader()
                    except Exception as e:
                        self._reply(f"🚨 Error al inicializar trader: <code>{e}</code>")
                        return
                self.bot.dry_run = False
                self._reply(f"{emoji} <b>OVERRIDE GLOBAL: {label}</b>\n\n{desc}\n\n⚠️ Aun asi cada wallet necesita estar en modo live individualmente.")
            else:
                self.bot.dry_run = True
                self._reply(f"{emoji} <b>OVERRIDE GLOBAL: {label}</b>\n\n{desc}\n\nTodas las wallets quedan bloqueadas en dry hasta que desactives el override.")
            return

        # With args = set mode for specific wallet
        address, nickname = self._resolve_monitored_wallet(args)
        if not address:
            self._reply(f"⚠️ No se encontro <b>{' '.join(args)}</b> en las wallets monitoreadas.")
            return

        # For live mode, ensure Trader is initialized
        if mode == "live" and self.bot.trader is None:
            try:
                from trader import Trader
                self.bot.trader = Trader()
            except Exception as e:
                self._reply(f"🚨 Error al inicializar trader: <code>{e}</code>")
                return

        wallet_manager.set_mode(address, mode)

        self._reply(
            f"{'━' * 28}\n"
            f"{emoji} <b>MODO {label}</b>\n"
            f"{'━' * 28}\n\n"
            f"👤 <b>{nickname}</b>\n"
            f"<code>{address}</code>\n\n"
            f"{desc}"
        )

    def _cmd_demo_balance(self):
        """Show demo account summary."""
        s = self.bot.demo.get_summary()
        pnl = s["total_pnl"]
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        ret_str = f"+{s['total_return_pct']:.1f}%" if s['total_return_pct'] >= 0 else f"{s['total_return_pct']:.1f}%"
        emoji = "📈" if pnl >= 0 else "📉"

        text = (
            f"{'━' * 28}\n"
            f"🎮 <b>CUENTA DEMO</b>\n"
            f"{'━' * 28}\n\n"
            f"💰 Balance disponible: <b>${s['balance']:,.2f}</b>\n"
            f"📊 En posiciones: ${s['in_positions']:,.2f}\n"
            f"🏦 Capital inicial: ${s['initial_balance']:,.2f}\n\n"
            f"{emoji} PnL realizado: <b>${s['realized_pnl']:,.2f}</b>\n"
            f"{emoji} PnL no realizado: <b>${s['unrealized_pnl']:,.2f}</b>\n"
            f"{'━' * 20}\n"
            f"{emoji} PnL total: <b>{pnl_str}</b> ({ret_str})\n"
        )

        if s["positions"]:
            text += f"\n📋 <b>Posiciones abiertas ({s['open_count']}):</b>\n"
            for p in s["positions"][:8]:
                pnl_p = p['pnl']
                em = "✅" if pnl_p >= 0 else "❌"
                nick = wallet_manager.get_nickname(p.get("source_wallet", ""))
                market = p["market_name"][:30]
                slug = p.get("slug", "")
                link = f'<a href="https://polymarket.com/market/{slug}">{market}</a>' if slug else market
                fee_str = f" fee=${p['fee']:.2f}" if p.get("fee") else ""
                text += (
                    f"  {em} {link}\n"
                    f"      entrada={p['entry_price']:.3f} actual={p['current_price']:.3f} "
                    f"PnL=<b>${pnl_p:,.2f}</b> ({p['pnl_pct']:+.1f}%) [{nick}]{fee_str}\n"
                )

        if s.get("closed_details"):
            text += f"\n📕 <b>Posiciones cerradas ({s['closed_count']}):</b>\n"
            for cp in s["closed_details"][-8:]:
                pnl_c = cp["pnl"]
                em_c = "💰" if pnl_c >= 0 else "💸"
                market_c = cp["market_name"][:30]
                slug_c = cp.get("slug", "")
                link_c = f'<a href="https://polymarket.com/market/{slug_c}">{market_c}</a>' if slug_c else market_c
                fee_str = f" | fee=${cp['fee']:.2f}" if cp.get("fee") else ""
                text += (
                    f"  {em_c} {link_c}\n"
                    f"      {cp['entry_price']:.3f}→{cp['exit_price']:.3f} "
                    f"${cp['cost']:.2f}→${cp['proceeds']:.2f} "
                    f"PnL=<b>${pnl_c:,.2f}</b> ({cp['pnl_pct']:+.1f}%){fee_str}\n"
                    f"      {cp['close_reason']} | {cp['duration']}\n"
                )
        elif s["closed_count"] > 0:
            text += f"\n✔️ Posiciones cerradas: {s['closed_count']}"

        # Fee summary
        total_fees = s.get("total_fees", 0)
        if total_fees > 0:
            text += f"\n💳 <b>Fees estimados pagados: ${total_fees:,.4f}</b>"

        self._reply(text)

    def _cmd_demo_reset(self, args: list[str]):
        """Reset the demo account."""
        import config as _cfg
        balance = float(args[0]) if args else _cfg.DEMO_BALANCE
        self.bot.demo.reset(balance)
        self._reply(
            f"{'━' * 28}\n"
            f"🎮 <b>CUENTA DEMO REINICIADA</b>\n"
            f"{'━' * 28}\n\n"
            f"💰 Nuevo balance: <b>${balance:,.2f}</b>\n"
            f"Todas las posiciones demo han sido borradas."
        )

    def _send_document(self, file_path: str, caption: str = ""):
        """Send a file as a Telegram document."""
        import os
        try:
            with open(file_path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument",
                    data={
                        "chat_id": config.TELEGRAM_CHAT_ID,
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                    files={"document": (os.path.basename(file_path), f)},
                    timeout=30,
                )
        except Exception as e:
            self._reply(f"Error enviando archivo: <code>{e}</code>")

    def _cmd_demo_export(self):
        """Export demo account data as JSON file via Telegram."""
        import json
        import os
        import tempfile
        import time as _time

        self._reply("📦 Generando export de cuenta demo...")

        summary = self.bot.demo.get_summary()

        export = {
            "summary": {
                "balance": summary["balance"],
                "initial_balance": summary["initial_balance"],
                "in_positions": summary["in_positions"],
                "open_count": summary["open_count"],
                "closed_count": summary["closed_count"],
                "realized_pnl": summary["realized_pnl"],
                "unrealized_pnl": summary["unrealized_pnl"],
                "total_pnl": summary["total_pnl"],
                "total_return_pct": summary["total_return_pct"],
                "total_fees": summary.get("total_fees", 0),
            },
            "open_positions": self.bot.demo.positions,
            "closed_positions": self.bot.demo.closed_positions,
            "exported_at": _time.time(),
        }

        tmp = os.path.join(tempfile.gettempdir(), "demo_export.json")
        with open(tmp, "w") as f:
            json.dump(export, f, indent=2, default=str)

        pnl = summary["total_pnl"]
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        fees = summary.get("total_fees", 0)
        caption = (
            f"🎮 Demo Export\n"
            f"Balance: ${summary['balance']:,.2f} | PnL: {pnl_str}\n"
            f"Posiciones: {summary['open_count']} abiertas, {summary['closed_count']} cerradas\n"
            f"Fees estimados: ${fees:,.4f}"
        )
        self._send_document(tmp, caption)

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

        mode_icons = {"dry": "🔬", "demo": "🎮", "live": "⚡"}
        lines = []
        for w in wallets:
            addr = w["address"]
            nick = w.get("nickname") or f"{addr[:10]}...{addr[-6:]}"
            manually_paused = wallet_manager.is_paused(addr)
            auto_paused = self.bot.reliability.is_wallet_paused(addr)
            wmode = wallet_manager.get_mode(addr)
            mode_icon = mode_icons.get(wmode, "🔬")

            if manually_paused:
                status = f" {mode_icon} [<b>{wmode.upper()}</b>] ⏸ <i>pausada</i>"
            elif auto_paused:
                status = f" {mode_icon} [<b>{wmode.upper()}</b>] ⚠️ <i>bajo rendimiento</i>"
            else:
                status = f" {mode_icon} [<b>{wmode.upper()}</b>]"

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
