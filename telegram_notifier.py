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
        emoji = "😅"
        comment = "Nos la perdimos"
    elif pnl_pct < 0:
        verdict = f"📉 Hubiera sido <b>PERDIDA</b> ({pnl_pct:.1f}%)"
        emoji = "😌"
        comment = "Buena decision saltarlo"
    else:
        verdict = "➡️ <b>Sin cambio</b>"
        emoji = "😐"
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


# ─── ERRORS ──────────────────────────────────────────────

def notify_error(error: str):
    _send(
        f"{'━' * 28}\n"
        f"🚨 <b>ERROR</b>\n"
        f"{'━' * 28}\n\n"
        f"<code>{error[:500]}</code>"
    )
