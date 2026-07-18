import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    
    # Email
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    
    # Twilio
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Calendly
    CALENDLY_TOKEN = os.getenv('CALENDLY_TOKEN')
    CALENDLY_USER_UUID = os.getenv('CALENDLY_USER_UUID')

    # Automatic on-chain payment verification (see payment_verifier.py)
    ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY')       # required for ETH/USDT/USDC verification
    BLOCKCYPHER_TOKEN = os.getenv('BLOCKCYPHER_TOKEN')        # optional, raises LTC/DOGE rate limits
    SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
    USDT_CONTRACT_ADDRESS = os.getenv('USDT_CONTRACT_ADDRESS')  # override if not mainnet Ethereum USDT
    USDC_CONTRACT_ADDRESS = os.getenv('USDC_CONTRACT_ADDRESS')  # override if not mainnet Ethereum USDC

    # WalletConnect (Reown Cloud) — free project ID from https://cloud.reown.com
    # Powers the "Pay with WalletConnect" QR option so mobile wallets (not just
    # browser extensions) can pay in one tap. Without this set, that button is hidden
    # and only the MetaMask/Phantom browser-extension buttons + manual QR still show.
    WALLETCONNECT_PROJECT_ID = os.getenv('WALLETCONNECT_PROJECT_ID')