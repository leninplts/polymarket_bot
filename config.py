import os
from dotenv import load_dotenv

load_dotenv()


PRIVATE_KEY = os.environ["PRIVATE_KEY"]
TARGET_WALLETS = [w.strip().lower() for w in os.environ["TARGET_WALLETS"].split(",") if w.strip()]

SIZING_MODE = os.getenv("SIZING_MODE", "fixed")  # "fixed" or "proportional"
FIXED_AMOUNT = float(os.getenv("FIXED_AMOUNT", "10"))
PROPORTIONAL_FACTOR = float(os.getenv("PROPORTIONAL_FACTOR", "0.1"))

# Scaling: follow the trader when they keep adding to the same position
# MAX_POSITION_PCT: max % of FIXED_AMOUNT*10 we'll put in a single market (default 20% = 2x FIXED_AMOUNT)
# SCALE_ON_CONVICTION: only scale if trader's new order price >= our last entry price (price going up = conviction)
# Without this flag we'd average down on losing positions too
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.20"))  # 20% of total budget per market
SCALE_ON_CONVICTION = os.getenv("SCALE_ON_CONVICTION", "true").lower() == "true"

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.02"))

FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")

CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

CHAIN_ID = 137  # Polygon mainnet

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
