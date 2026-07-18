# payment_verifier.py - automatic on-chain payment detection.
#
# For each pending order we look at its destination wallet address and ask a public
# block explorer whether an incoming transaction matches the order's uniquely-tagged
# amount (see payments.py: create_payment tags every order with a few extra decimals
# so multiple orders can share one wallet address and still be told apart).
#
# Each check_* function returns a list of dicts: {'tx_hash', 'amount', 'confirmations'}
# for recent incoming transfers to that address. Network/parsing errors are caught and
# logged rather than raised, so one flaky API call doesn't take down the whole poller.

import os
import requests

REQUEST_TIMEOUT = 15

ETHERSCAN_API_KEY = os.environ.get('ETHERSCAN_API_KEY', '')
BLOCKCYPHER_TOKEN = os.environ.get('BLOCKCYPHER_TOKEN', '')  # optional, raises free rate limit
SOLANA_RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Mainnet ERC-20 contract addresses (override via env if you use different tokens/chains)
ERC20_CONTRACTS = {
    'USDT': os.environ.get('USDT_CONTRACT_ADDRESS', '0xdAC17F958D2ee523a2206206994597C13D831ec'),
    'USDC': os.environ.get('USDC_CONTRACT_ADDRESS', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'),
}

# How many confirmations we require before auto-granting access, per chain.
# Override any of these with e.g. CONFIRMATIONS_REQUIRED_BTC=3 in the environment.
DEFAULT_CONFIRMATIONS_REQUIRED = {
    'BTC': 2,
    'ETH': 12,
    'USDT': 12,
    'USDC': 12,
    'SOL': 1,
    'LTC': 6,
    'DOGE': 6,
}


def confirmations_required(crypto_currency):
    override = os.environ.get(f'CONFIRMATIONS_REQUIRED_{crypto_currency.upper()}')
    if override:
        return int(override)
    return DEFAULT_CONFIRMATIONS_REQUIRED.get(crypto_currency.upper(), 2)


# ------------------------------------------------------------------
# BTC - blockstream.info
# ------------------------------------------------------------------
def check_btc(address):
    try:
        tip = requests.get('https://blockstream.info/api/blocks/tip/height', timeout=REQUEST_TIMEOUT)
        tip.raise_for_status()
        tip_height = int(tip.text)

        resp = requests.get(f'https://blockstream.info/api/address/{address}/txs', timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        txs = resp.json()

        results = []
        for tx in txs:
            received = sum(
                vout.get('value', 0) for vout in tx.get('vout', [])
                if vout.get('scriptpubkey_address') == address
            )
            if received <= 0:
                continue
            status = tx.get('status', {})
            if status.get('confirmed'):
                confs = tip_height - status.get('block_height', tip_height) + 1
            else:
                confs = 0
            results.append({
                'tx_hash': tx.get('txid'),
                'amount': received / 1e8,
                'confirmations': max(confs, 0),
            })
        return results
    except Exception as e:
        print(f"⚠️ BTC verification error for {address}: {e}")
        return []


# ------------------------------------------------------------------
# LTC / DOGE - blockcypher
# ------------------------------------------------------------------
def check_blockcypher(address, chain):
    """chain: 'ltc' or 'doge'"""
    try:
        params = {'limit': 50}
        if BLOCKCYPHER_TOKEN:
            params['token'] = BLOCKCYPHER_TOKEN
        resp = requests.get(
            f'https://api.blockcypher.com/v1/{chain}/main/addrs/{address}/full',
            params=params, timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for tx in data.get('txs', []):
            received = 0
            for out in tx.get('outputs', []):
                if address in out.get('addresses', []):
                    received += out.get('value', 0)
            if received <= 0:
                continue
            results.append({
                'tx_hash': tx.get('hash'),
                'amount': received / 1e8,
                'confirmations': tx.get('confirmations', 0),
            })
        return results
    except Exception as e:
        print(f"⚠️ {chain.upper()} verification error for {address}: {e}")
        return []


def check_ltc(address):
    return check_blockcypher(address, 'ltc')


def check_doge(address):
    return check_blockcypher(address, 'doge')


# ------------------------------------------------------------------
# ETH native - etherscan
# ------------------------------------------------------------------
def check_eth(address):
    if not ETHERSCAN_API_KEY:
        print("⚠️ ETHERSCAN_API_KEY not set, skipping ETH verification")
        return []
    try:
        resp = requests.get(
            'https://api.etherscan.io/api',
            params={
                'module': 'account', 'action': 'txlist', 'address': address,
                'sort': 'desc', 'apikey': ETHERSCAN_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for tx in data.get('result', []) or []:
            if not isinstance(tx, dict):
                continue
            if tx.get('to', '').lower() != address.lower():
                continue
            if tx.get('isError') != '0':
                continue
            value = int(tx.get('value', 0))
            if value <= 0:
                continue
            results.append({
                'tx_hash': tx.get('hash'),
                'amount': value / 1e18,
                'confirmations': int(tx.get('confirmations', 0)),
            })
        return results
    except Exception as e:
        print(f"⚠️ ETH verification error for {address}: {e}")
        return []


# ------------------------------------------------------------------
# ERC-20 (USDT / USDC) - etherscan token transfers
# ------------------------------------------------------------------
def check_erc20(address, symbol):
    if not ETHERSCAN_API_KEY:
        print("⚠️ ETHERSCAN_API_KEY not set, skipping {symbol} verification")
        return []
    contract = ERC20_CONTRACTS.get(symbol.upper())
    if not contract:
        print(f"⚠️ No contract address configured for {symbol}")
        return []
    try:
        current_block_resp = requests.get(
            'https://api.etherscan.io/api',
            params={'module': 'proxy', 'action': 'eth_blockNumber', 'apikey': ETHERSCAN_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        current_block_resp.raise_for_status()
        current_block = int(current_block_resp.json().get('result', '0x0'), 16)

        resp = requests.get(
            'https://api.etherscan.io/api',
            params={
                'module': 'account', 'action': 'tokentx', 'address': address,
                'contractaddress': contract, 'sort': 'desc', 'apikey': ETHERSCAN_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for tx in data.get('result', []) or []:
            if not isinstance(tx, dict):
                continue
            if tx.get('to', '').lower() != address.lower():
                continue
            decimals = int(tx.get('tokenDecimal', 6))
            value = int(tx.get('value', 0))
            if value <= 0:
                continue
            tx_block = int(tx.get('blockNumber', current_block))
            confs = max(current_block - tx_block, 0)
            results.append({
                'tx_hash': tx.get('hash'),
                'amount': value / (10 ** decimals),
                'confirmations': confs,
            })
        return results
    except Exception as e:
        print(f"⚠️ {symbol} verification error for {address}: {e}")
        return []


# ------------------------------------------------------------------
# SOL - public Solana RPC
# ------------------------------------------------------------------
def check_sol(address):
    try:
        sig_resp = requests.post(
            SOLANA_RPC_URL, timeout=REQUEST_TIMEOUT,
            json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'getSignaturesForAddress',
                'params': [address, {'limit': 25}],
            },
        )
        sig_resp.raise_for_status()
        signatures = sig_resp.json().get('result', []) or []

        results = []
        for sig_info in signatures:
            if sig_info.get('err'):
                continue
            signature = sig_info.get('signature')
            status = sig_info.get('confirmationStatus', '')
            confs = 1 if status in ('confirmed', 'finalized') else 0

            tx_resp = requests.post(
                SOLANA_RPC_URL, timeout=REQUEST_TIMEOUT,
                json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'getTransaction',
                    'params': [signature, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 0}],
                },
            )
            tx_resp.raise_for_status()
            tx = tx_resp.json().get('result')
            if not tx:
                continue

            meta = tx.get('meta', {})
            account_keys = [
                k.get('pubkey') if isinstance(k, dict) else k
                for k in tx.get('transaction', {}).get('message', {}).get('accountKeys', [])
            ]
            if address not in account_keys:
                continue
            idx = account_keys.index(address)
            pre = meta.get('preBalances', [None] * len(account_keys))[idx]
            post = meta.get('postBalances', [None] * len(account_keys))[idx]
            if pre is None or post is None:
                continue
            received = (post - pre) / 1e9
            if received <= 0:
                continue
            results.append({'tx_hash': signature, 'amount': received, 'confirmations': confs})
        return results
    except Exception as e:
        print(f"⚠️ SOL verification error for {address}: {e}")
        return []


# ------------------------------------------------------------------
# Dispatcher
# ------------------------------------------------------------------
def get_incoming_transactions(address, crypto_currency):
    crypto_currency = crypto_currency.upper()
    if crypto_currency == 'BTC':
        return check_btc(address)
    if crypto_currency == 'ETH':
        return check_eth(address)
    if crypto_currency in ('USDT', 'USDC'):
        return check_erc20(address, crypto_currency)
    if crypto_currency == 'LTC':
        return check_ltc(address)
    if crypto_currency == 'DOGE':
        return check_doge(address)
    if crypto_currency == 'SOL':
        return check_sol(address)
    print(f"⚠️ No verifier implemented for {crypto_currency}")
    return []


def find_matching_transaction(pay_to_address, crypto_currency, target_amount, tolerance=5e-7):
    """Look for an incoming tx to `pay_to_address` whose amount matches `target_amount`
    within `tolerance`. Returns the best (highest-confirmation) match, or None."""
    if not pay_to_address or target_amount is None:
        return None
    txs = get_incoming_transactions(pay_to_address, crypto_currency)
    matches = [tx for tx in txs if abs(tx['amount'] - float(target_amount)) <= tolerance]
    if not matches:
        return None
    return max(matches, key=lambda tx: tx['confirmations'])
