"""Telegram notification module for the copy-trading bot."""

import requests
import config

# Counter for skipped trades
_skip_counter = 0


def _send(text: str, parse_mode: str = "HTML"):
    """Send a message to the configured Telegram chat."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[telegram] Error sending message: {e}")


def _trader_link(wallet: str) -> str:
    try:
        import wallet_manager
        nick = wallet_manager.get_nickname(wallet)
    except Exception:
        nick = f"{wallet[:10]}...{wallet[-6:]}"
    return f'<a href="https://polymarket.com/profile/{wallet}">{nick}</a>'


def _market_link(market_name: str, slug: str = None, event_slug: str = None) -> str:
    s = slug or event_slug
    if s:
        return f'<a href="https://polymarket.com/market/{s}">{market_name}</a>'
    return market_name


# ─── BOT LIFECYCLE ───────────────────────────────────────

def notify_bot_started(wallets: list[str], dry_run: bool):
    mode = "🔬 SIMULACION" if dry_run else "⚡ EN VIVO"
    wallet_list = "\n".join(f"    └ {_trader_link(w)}" for w in wallets)
    _send(
        f"{'━' * 28}\n"
        f"🚀 <b>BOT INICIADO</b>  │  {mode}\n"
        f"{'━' * 28}\n\n"
        f"👁 Monitoreando {len(wallets)} wallet(s):\n{wallet_list}\n\n"
        f"💰 Sizing: <b>{config.SIZING_MODE}</b> "
        f"({'$' + str(config.FIXED_AMOUNT) if config.SIZING_MODE == 'fixed' else str(config.PROPORTIONAL_FACTOR) + 'x'})\n"
        f"📊 Max slippage: <b>{config.MAX_SLIPPAGE:.1%}</b>\n"
        f"⏱ Poll: cada <b>{config.POLL_INTERVAL}s</b>"
    )


def notify_shutdown(stats: dict):
    _send(
        f"{'━' * 28}\n"
        f"🛑 <b>BOT DETENIDO</b>\n"
        f"{'━' * 28}\n\n"
        f"📋 <b>Resumen de sesion:</b>\n"
        f"    Detectados:  {stats.get('trades_detected', 0)}\n"
        f"    Copiados:    {stats.get('trades_copied', 0)}\n"
        f"    Saltados:    {stats.get('trades_skipped', 0)}"
    )


# ─── TRADE DETECTED ─────────────────────────────────────

def notify_trade_detected(trade: dict, market_name: str, slug: str = None, event_slug: str = None):
    wallet = trade.get("wallet", "?")
    side = trade.get("side", "?")
    size = trade.get("size", 0)
    price = trade.get("price", 0)
    outcome = trade.get("outcome", "?")

    arrow = "🟢 COMPRA" if side == "BUY" else "🔴 VENTA"
    market_display = _market_link(market_name, slug, event_slug)

    _send(
        f"{'━' * 28}\n"
        f"🔔 <b>TRADE DETECTADO</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 {_trader_link(wallet)}\n"
        f"📌 {market_display}\n\n"
        f"    {arrow}\n"
        f"    💵 Size: <b>${size:,.2f}</b>\n"
        f"    🎯 Precio: <b>{price}</b>\n"
        f"    📍 Outcome: <b>{outcome}</b>"
    )


# ─── TRADE COPIED (green accent) ────────────────────────

def notify_trade_copied(trade: dict, market_name: str, our_size: float, our_price: float, result: dict, slug: str = None, event_slug: str = None):
    side = trade.get("side", "?")
    wallet = trade.get("wallet", "?")
    arrow = "🟢 COMPRA" if side == "BUY" else "🔴 VENTA"
    order_id = result.get("orderID") or result.get("id") or "?"
    market_display = _market_link(market_name, slug, event_slug)

    _send(
        f"{'━' * 28}\n"
        f"✅ <b>TRADE COPIADO</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 {_trader_link(wallet)}\n"
        f"📌 {market_display}\n"
        f"    {arrow}\n\n"
        f"┌─ <b>Nuestra orden</b>\n"
        f"│  💵 Size: <b>${our_size:,.2f}</b>\n"
        f"│  🎯 Precio: <b>{our_price}</b>\n"
        f"└─ ID: <code>{order_id}</code>\n\n"
        f"┌─ <b>Orden original</b>\n"
        f"│  💵 Size: ${trade.get('size', 0):,.2f}\n"
        f"└─ 🎯 Precio: {trade.get('price', 0)}"
    )


# ─── TRADE SKIPPED (gray/yellow accent) ─────────────────

def notify_trade_skipped(trade: dict, market_name: str, reason: str, slug: str = None, event_slug: str = None):
    global _skip_counter
    _skip_counter += 1

    side = trade.get("side", "?")
    size = trade.get("size", 0)
    price = trade.get("price", 0)
    wallet = trade.get("wallet", "?")
    market_display = _market_link(market_name, slug, event_slug)

    _send(
        f"{'━' * 28}\n"
        f"⏭ <b>TRADE SALTADO</b>  │  #{_skip_counter}\n"
        f"{'━' * 28}\n\n"
        f"👤 {_trader_link(wallet)}\n"
        f"📌 {market_display}\n"
        f"    {'🟢' if side == 'BUY' else '🔴'} {side}  │  ${size:,.2f} @ {price}\n\n"
        f"⚠️ <b>Razon:</b> {reason}"
    )


# ─── SKIPPED TRADE OUTCOME ──────────────────────────────

def notify_skipped_outcome(skip_number: int, trade: dict, market_name: str, entry_price: float, current_price: float, slug: str = None, event_slug: str = None):
    """Called later to show if a skipped trade would have won or lost."""
    side = trade.get("side", "?")
    market_display = _market_link(market_name, slug, event_slug)

    if side == "BUY":
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    else:
        pnl_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price > 0 else 0

    if pnl_pct > 0:
        verdict = f"📈 Hubiera sido <b>GANANCIA</b> (+{pnl_pct:.1f}%)"
        emoji = "😅😅😅"
        comment = "Nos la perdimos"
    elif pnl_pct < 0:
        verdict = f"📉 Hubiera sido <b>PERDIDA</b> ({pnl_pct:.1f}%)"
        emoji = "😌😌😌"
        comment = "Buena decision saltarlo"
    else:
        verdict = "➡️ <b>Sin cambio</b>"
        emoji = "😐😐😐"
        comment = "Neutral"

    _send(
        f"{'━' * 28}\n"
        f"{emoji} <b>RESULTADO SALTADO</b>  │  #{skip_number}\n"
        f"{'━' * 28}\n\n"
        f"📌 {market_display}\n"
        f"    Precio entrada: {entry_price}\n"
        f"    Precio actual:  {current_price}\n\n"
        f"    {verdict}\n"
        f"    💬 {comment}"
    )


def get_skip_counter() -> int:
    return _skip_counter


# ─── POSITION CLOSED ────────────────────────────────────

def notify_position_closed(position: dict, exit_price: float, reason: str, slug: str = None, event_slug: str = None):
    """Notification when a position is closed (exit copy or stop-loss)."""
    market_name = position.get("market_name", "Unknown")
    market_display = _market_link(market_name, slug, event_slug)
    entry_price = position.get("entry_price", 0)
    pnl = position.get("pnl", 0)
    size = position.get("size", 0)
    source = position.get("source_wallet", "")

    if entry_price > 0:
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        pnl_pct = 0

    # Duration
    opened = position.get("opened_at", 0)
    closed = position.get("closed_at", 0)
    if opened and closed:
        duration_min = (closed - opened) / 60
        if duration_min < 60:
            duration = f"{duration_min:.0f} min"
        elif duration_min < 1440:
            duration = f"{duration_min / 60:.1f} horas"
        else:
            duration = f"{duration_min / 1440:.1f} dias"
    else:
        duration = "?"

    if pnl >= 0:
        emoji = "💰"
        header = "POSICION CERRADA — GANANCIA"
        pnl_bar = "🟩" * min(int(abs(pnl_pct) / 5) + 1, 10)
    else:
        emoji = "💸"
        header = "POSICION CERRADA — PERDIDA"
        pnl_bar = "🟥" * min(int(abs(pnl_pct) / 5) + 1, 10)

    trader_line = f"\n👤 {_trader_link(source)}" if source else ""

    text = (
        f"{'━' * 28}\n"
        f"{emoji} <b>{header}</b>\n"
        f"{'━' * 28}\n\n"
        f"📌 {market_display}{trader_line}\n"
        f"    {pnl_bar}\n\n"
        f"    Entrada: {entry_price}\n"
        f"    Salida:  {exit_price}\n"
        f"    Size:    ${size:.2f}\n"
        f"    PnL:     <b>${pnl:,.2f}</b> ({pnl_pct:+.1f}%)\n"
        f"    Duracion: {duration}\n\n"
        f"    📋 Razon: {reason}"
    )

    _send(text)


# ─── COPIED TRADE RESULT ────────────────────────────────

def notify_position_update(market_name: str, side: str, entry_price: float, current_price: float, our_size: float, slug: str = None, event_slug: str = None):
    """Periodic update on a copied position."""
    market_display = _market_link(market_name, slug, event_slug)

    if side == "BUY":
        pnl = (current_price - entry_price) * our_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    else:
        pnl = (entry_price - current_price) * our_size
        pnl_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price > 0 else 0

    if pnl >= 0:
        bar = "🟩" * min(int(pnl_pct / 5) + 1, 10) + "⬜" * max(10 - int(pnl_pct / 5) - 1, 0)
        emoji = "💚"
    else:
        bar = "🟥" * min(int(abs(pnl_pct) / 5) + 1, 10) + "⬜" * max(10 - int(abs(pnl_pct) / 5) - 1, 0)
        emoji = "💔"

    _send(
        f"{'━' * 28}\n"
        f"{emoji} <b>POSICION ABIERTA</b>\n"
        f"{'━' * 28}\n\n"
        f"📌 {market_display}\n"
        f"    {bar}\n\n"
        f"    Entrada:  {entry_price}\n"
        f"    Actual:   {current_price}\n"
        f"    PnL:      <b>${pnl:,.2f}</b> ({pnl_pct:+.1f}%)"
    )


# ─── PNL SUMMARY (periodic) ─────────────────────────────

def notify_pnl_update(stats: dict, positions: list[dict] = None):
    copied = stats.get("trades_copied", 0)
    skipped = stats.get("trades_skipped", 0)
    detected = stats.get("trades_detected", 0)
    pnl = stats.get("total_pnl", 0)

    emoji = "📈" if pnl >= 0 else "📉"

    text = (
        f"{'━' * 28}\n"
        f"{emoji} <b>RESUMEN PERIODICO</b>\n"
        f"{'━' * 28}\n\n"
        f"    Detectados:  {detected}\n"
        f"    Copiados:    {copied}\n"
        f"    Saltados:    {skipped}\n"
        f"    PnL total:   <b>${pnl:,.2f}</b>\n"
    )

    if positions:
        text += "\n📋 <b>Posiciones:</b>\n"
        for p in positions[:5]:
            em = "✅" if p.get("pnl", 0) >= 0 else "❌"
            text += f"    {em} {p.get('market', '?')[:30]} → <b>${p.get('pnl', 0):,.2f}</b>\n"

    _send(text)


# ─── TRADER RELIABILITY ─────────────────────────────────

def notify_trader_performance(wallet: str, recent_wr: float, recent_pnl: float, action: str):
    if action == "pause":
        emoji = "🚨"
        header = "TRADER PAUSADO"
        msg = "Rendimiento bajo, dejamos de copiar"
    else:
        emoji = "✅"
        header = "TRADER ACTIVO"
        msg = "Rendimiento estable, seguimos copiando"

    _send(
        f"{'━' * 28}\n"
        f"{emoji} <b>{header}</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 {_trader_link(wallet)}\n"
        f"    Win rate reciente: <b>{recent_wr:.0%}</b>\n"
        f"    PnL reciente: <b>${recent_pnl:,.2f}</b>\n\n"
        f"    💬 {msg}"
    )


# ─── SCALE INTO POSITION ────────────────────────────────

def notify_trade_scaled(nickname: str, market_name: str, extra_size: float,
                        new_price: float, avg_entry: float,
                        total_invested: float, max_allowed: float,
                        slug: str = None, event_slug: str = None):
    """Notification when we scale into an existing position."""
    market_display = _market_link(market_name, slug, event_slug)
    usdc_added = round(extra_size * new_price, 2)
    pct_used = round(total_invested / max_allowed * 100) if max_allowed > 0 else 0
    bar_filled = int(pct_used / 10)
    cap_bar = "🟦" * bar_filled + "⬜" * (10 - bar_filled)

    _send(
        f"{'━' * 28}\n"
        f"📈 <b>POSICION ESCALADA</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 <b>{nickname}</b>\n"
        f"📌 {market_display}\n\n"
        f"    ➕ Agregado: <b>${usdc_added:,.2f}</b> @ {new_price:.3f}\n"
        f"    📊 Precio promedio: <b>{avg_entry:.3f}</b>\n"
        f"    💵 Total invertido: <b>${total_invested:,.2f}</b> / ${max_allowed:,.2f}\n"
        f"    {cap_bar} {pct_used}% del tope"
    )


# ─── DEMO NOTIFICATIONS ─────────────────────────────────

def notify_demo_buy(trade: dict, market_name: str, cost: float, price: float,
                    balance: float, slug: str = None, event_slug: str = None):
    wallet = trade.get("wallet", "")
    market_display = _market_link(market_name, slug, event_slug)
    outcome = trade.get("outcome", "?")
    _send(
        f"{'━' * 28}\n"
        f"🎮 <b>DEMO — COMPRA</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 {_trader_link(wallet)}\n"
        f"📌 {market_display}\n\n"
        f"    💵 Invertido: <b>${cost:,.2f}</b> @ {price:.3f}\n"
        f"    📍 Outcome: <b>{outcome}</b>\n"
        f"    🏦 Balance restante: <b>${balance:,.2f}</b>"
    )


def notify_demo_scaled(nickname: str, market_name: str, new_price: float,
                       avg_entry: float, total_invested: float, max_allowed: float,
                       balance: float, slug: str = None, event_slug: str = None):
    market_display = _market_link(market_name, slug, event_slug)
    pct_used = round(total_invested / max_allowed * 100) if max_allowed > 0 else 0
    bar = "🟦" * min(pct_used // 10, 10) + "⬜" * max(10 - pct_used // 10, 0)
    _send(
        f"{'━' * 28}\n"
        f"🎮 <b>DEMO — ESCALADA</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 <b>{nickname}</b>\n"
        f"📌 {market_display}\n\n"
        f"    🎯 Precio actual: {new_price:.3f}\n"
        f"    📊 Precio promedio: {avg_entry:.3f}\n"
        f"    💵 Total en posicion: <b>${total_invested:,.2f}</b> / ${max_allowed:,.2f}\n"
        f"    {bar} {pct_used}%\n"
        f"    🏦 Balance: <b>${balance:,.2f}</b>"
    )


def notify_demo_closed(position: dict, exit_price: float, reason: str,
                       balance: float, slug: str = None, event_slug: str = None):
    market_name = position.get("market_name", "Unknown")
    market_display = _market_link(market_name, slug, event_slug)
    entry_price = position.get("entry_price", 0)
    pnl = position.get("pnl", 0)
    cost = position.get("cost", 0)
    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 1) if entry_price > 0 else 0
    emoji = "💰" if pnl >= 0 else "💸"
    header = "DEMO — GANANCIA" if pnl >= 0 else "DEMO — PERDIDA"

    opened = position.get("opened_at", 0)
    closed_at = position.get("closed_at", 0)
    if opened and closed_at:
        duration_min = (closed_at - opened) / 60
        duration = f"{duration_min:.0f}min" if duration_min < 60 else f"{duration_min/60:.1f}h"
    else:
        duration = "?"

    source = position.get("source_wallet", "")
    trader_line = f"\n👤 {_trader_link(source)}" if source else ""
    _send(
        f"{'━' * 28}\n"
        f"🎮 {emoji} <b>{header}</b>\n"
        f"{'━' * 28}\n\n"
        f"📌 {market_display}{trader_line}\n\n"
        f"    Entrada: {entry_price:.3f} → Salida: {exit_price:.3f}\n"
        f"    Invertido: ${cost:,.2f}\n"
        f"    PnL: <b>${pnl:,.2f}</b> ({pnl_pct:+.1f}%)\n"
        f"    Duracion: {duration}\n"
        f"    📋 {reason}\n\n"
        f"    🏦 Balance demo: <b>${balance:,.2f}</b>"
    )


# ─── TRADE BUFFER SUMMARY ───────────────────────────────

def notify_trade_buffer_summary(nickname: str, market_name: str, count: int,
                                 total_usdc: float, total_size: float,
                                 first_price: float, last_price: float,
                                 slug: str = None, event_slug: str = None):
    """Summary sent 60s after the first order, if there were multiple fragmented orders."""
    market_display = _market_link(market_name, slug, event_slug)
    avg_price = total_usdc / total_size if total_size > 0 else first_price

    _send(
        f"{'━' * 28}\n"
        f"📦 <b>RESUMEN DE ORDENES ({count} total)</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 <b>{nickname}</b>\n"
        f"📌 {market_display}\n\n"
        f"    💵 Total invertido: <b>${total_usdc:,.2f}</b>\n"
        f"    🎯 Precio inicial: {first_price:.3f} → Final: {last_price:.3f}\n"
        f"    📊 Precio promedio: {avg_price:.3f}\n"
        f"    📋 Ordenes fragmentadas: {count}"
    )


# ─── ERRORS ──────────────────────────────────────────────

def notify_error(error: str):
    _send(
        f"{'━' * 28}\n"
        f"🚨 <b>ERROR</b>\n"
        f"{'━' * 28}\n\n"
        f"<code>{error[:500]}</code>"
    )
