"""Execute copy-trades on Polymarket via the CLOB API."""

import config
import market_cache

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType


class Trader:
    def __init__(self):
        kwargs = {
            "host": config.CLOB_API_URL,
            "key": config.PRIVATE_KEY,
            "chain_id": config.CHAIN_ID,
        }
        if config.FUNDER_ADDRESS:
            kwargs["funder"] = config.FUNDER_ADDRESS

        self.client = ClobClient(**kwargs)
        self.creds = None
        self._setup_api_creds()

    def _setup_api_creds(self):
        """Derive or create API credentials from the private key."""
        try:
            self.creds = self.client.derive_api_key()
            print(f"[trader] API key derived successfully")
        except Exception:
            try:
                self.creds = self.client.create_api_key()
                print(f"[trader] API key created successfully")
            except Exception as e:
                print(f"[trader] Failed to set up API credentials: {e}")
                raise

        self.client.set_api_creds(self.creds)

    def _calculate_size(self, target_size: float) -> float:
        """Calculate our order size based on the sizing mode."""
        if config.SIZING_MODE == "fixed":
            return config.FIXED_AMOUNT
        elif config.SIZING_MODE == "proportional":
            return round(target_size * config.PROPORTIONAL_FACTOR, 2)
        return config.FIXED_AMOUNT

    def _get_current_price(self, token_id: str, side: str) -> float | None:
        """Get the current best price for a token."""
        try:
            book = self.client.get_order_book(token_id)
            if side == "BUY" and book.asks:
                return float(book.asks[0].price)
            elif side == "SELL" and book.bids:
                return float(book.bids[0].price)
        except Exception as e:
            print(f"[trader] Error fetching price for {token_id}: {e}")
        return None

    def execute_copy_trade(self, trade: dict) -> dict | None:
        """
        Execute a copy of the given trade.

        trade should contain: token_id, side, size, price
        """
        token_id = trade.get("token_id")
        if not token_id:
            print(f"[trader] Skipping trade with no token_id: {trade}")
            return None

        side = trade.get("side", "BUY")
        if side not in ("BUY", "SELL"):
            side = "BUY"

        our_size = self._calculate_size(trade.get("size", 0))
        if our_size <= 0:
            print(f"[trader] Calculated size is 0, skipping")
            return None

        # Get current market price and check slippage
        current_price = self._get_current_price(token_id, side)
        if current_price is None:
            print(f"[trader] Cannot get price for {token_id}, skipping")
            return None

        target_price = trade.get("price", current_price)
        if target_price > 0:
            slippage = abs(current_price - target_price) / target_price
            if slippage > config.MAX_SLIPPAGE:
                print(
                    f"[trader] Slippage too high ({slippage:.1%} > {config.MAX_SLIPPAGE:.1%}) "
                    f"for {token_id}, skipping"
                )
                return None

        # Get tick size for this market
        try:
            tick_size = self.client.get_tick_size(token_id)
        except Exception:
            tick_size = "0.01"

        # Build and place the order
        try:
            order_args = OrderArgs(
                price=current_price,
                size=our_size,
                side=side,
                token_id=token_id,
            )

            signed_order = self.client.create_order(order_args)
            result = self.client.post_order(signed_order, OrderType.GTC)

            market = market_cache.get_market_by_token(token_id)
            market_name = market.get("question", token_id) if market else token_id

            print(
                f"[trader] ORDER PLACED: {side} {our_size} @ {current_price} "
                f"on '{market_name}'"
            )
            return result

        except Exception as e:
            print(f"[trader] Failed to place order: {e}")
            return None

    def get_balance(self) -> dict | None:
        """Check USDC balance and allowance."""
        try:
            return self.client.get_balance_allowance()
        except Exception as e:
            print(f"[trader] Error fetching balance: {e}")
            return None

    def get_open_orders(self) -> list:
        """Get all open orders."""
        try:
            return self.client.get_orders()
        except Exception as e:
            print(f"[trader] Error fetching orders: {e}")
            return []

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        try:
            self.client.cancel_all()
            print("[trader] All orders cancelled")
            return True
        except Exception as e:
            print(f"[trader] Error cancelling orders: {e}")
            return False
