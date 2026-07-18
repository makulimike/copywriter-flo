# crypto_prices.py - fetch current USD prices for converting the USD list price
# into a native crypto amount (BTC/ETH/SOL/LTC/DOGE are not 1:1 with USD).

import time
import requests

_CACHE_TTL = 300  # 5 minutes
_cache = {}  # symbol -> (price, fetched_at)

# CoinGecko ids for the coins we support that aren't USD-pegged stablecoins
_COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'LTC': 'litecoin',
    'DOGE': 'dogecoin',
}

# Stablecoins we treat as 1:1 with USD
_STABLECOINS = {'USDT', 'USDC'}


def get_usd_price(symbol):
    """Return current USD price for 1 unit of `symbol`. Stablecoins are 1.0."""
    symbol = symbol.upper()
    if symbol in _STABLECOINS:
        return 1.0

    cached = _cache.get(symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL:
        return cached[0]

    coingecko_id = _COINGECKO_IDS.get(symbol)
    if not coingecko_id:
        raise ValueError(f"No price source configured for {symbol}")

    resp = requests.get(
        'https://api.coingecko.com/api/v3/simple/price',
        params={'ids': coingecko_id, 'vs_currencies': 'usd'},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    price = data[coingecko_id]['usd']

    _cache[symbol] = (price, time.time())
    return price


def usd_to_crypto(usd_amount, symbol):
    """Convert a USD amount into the equivalent amount of `symbol`."""
    price = get_usd_price(symbol)
    return usd_amount / price
