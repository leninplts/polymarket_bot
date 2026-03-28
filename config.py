import os
from dotenv import load_dotenv

load_dotenv()


PRIVATE_KEY = os.environ["PRIVATE_KEY"]
TARGET_WALLETS = [w.strip().lower() for w in os.environ["TARGET_WALLETS"].split(",") if w.strip()]

SIZING_MODE = os.getenv("SIZING_MODE", "fixed")  # "fixed" or "proportional"
FIXED_AMOUNT = float(os.getenv("FIXED_AMOUNT", "10"))
PROPORTIONAL_FACTOR = float(os.getenv("PROPORTIONAL_FACTOR", "0.1"))

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.02"))

FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")

CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

CHAIN_ID = 137  # Polygon mainnet

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
