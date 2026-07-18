# payments.py - Simple Crypto Payment with Direct Address & QR Codes

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from database import Database
import qrcode
import io
import base64
import random
from crypto_prices import usd_to_crypto
from payment_verifier import confirmations_required as get_confirmations_required

db = Database()

class CryptoPayment:
    """Simple crypto payment handler with direct wallet addresses and QR codes"""
    
    def __init__(self):
        # Wallet addresses from .env
        self.addresses = {
            'USDT': os.environ.get('USDT_ADDRESS', ''),
            'USDC': os.environ.get('USDC_ADDRESS', ''),
            'ETH': os.environ.get('ETH_ADDRESS', ''),
            'BTC': os.environ.get('BTC_ADDRESS', ''),
            'SOL': os.environ.get('SOL_ADDRESS', ''),
            'LTC': os.environ.get('LTC_ADDRESS', ''),
            'DOGE': os.environ.get('DOGE_ADDRESS', ''),
        }
        
        self.app_url = os.environ.get('APP_URL', 'http://localhost:5000')
        self.price_amount = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 280))
        self.price_currency = os.environ.get('CURRENCY', 'USD')
        self.db = db
        
        # Email settings
        self.smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER', '')
        self.smtp_password = os.environ.get('SMTP_PASSWORD', '')
        self.admin_email = os.environ.get('ADMIN_EMAIL', '')
        self.from_email = os.environ.get('SMTP_USER', '')
        
        # Supported currencies
        self.supported_currencies = ['BTC', 'ETH', 'USDT', 'USDC', 'SOL', 'LTC', 'DOGE']
        
        # Check which addresses are configured
        configured = [c for c, a in self.addresses.items() if a]
        print(f"✅ Crypto payments configured for: {', '.join(configured) if configured else 'None'}")
        print(f"📧 Admin email: {self.admin_email}")
    
    def _send_email(self, to_email, subject, body, html_body=None):
        """Send email using SMTP configuration"""
        if not self.smtp_user or not self.smtp_password:
            print(f"📧 Email not sent (SMTP not configured): {to_email}")
            return False
        
        if not to_email:
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email or self.smtp_user
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))
            if html_body:
                msg.attach(MIMEText(html_body, 'html'))
            
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email sent to {to_email}")
            return True
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
            return False
    
    def generate_qr_code(self, address, amount, crypto):
        """Generate QR code for payment"""
        # Different formats for different cryptocurrencies
        if crypto == 'BTC':
            uri = f"bitcoin:{address}?amount={amount}"
        elif crypto == 'ETH':
            uri = f"ethereum:{address}?value={amount}"
        elif crypto == 'SOL':
            uri = f"solana:{address}?amount={amount}"
        elif crypto in ['USDT', 'USDC']:
            # For stablecoins, use ERC20 format
            uri = f"ethereum:{address}?value={amount}"
        else:
            uri = f"{crypto.lower()}:{address}?amount={amount}"
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    def get_address(self, crypto_currency):
        """Get wallet address for a cryptocurrency"""
        return self.addresses.get(crypto_currency, '')

    def _build_payment_email(self, username, order_id, address, crypto_currency, amount, currency, qr_code, payment_url):
        """Build plain-text and HTML bodies for the payment instructions email"""
        text_body = (
            f"Hi {username},\n\n"
            f"Here are your payment details for Copywriterflo Lifetime Access:\n\n"
            f"Amount to send (exact): {amount} {currency}\n"
            f"Wallet address: {address}\n"
            f"Order ID: {order_id}\n\n"
            f"View this payment (QR code and live status) here:\n{payment_url}\n\n"
            f"Please send the EXACT amount shown above — it's how we automatically detect and confirm "
            f"your payment. Access unlocks automatically once your payment is detected on-chain, no "
            f"further action needed.\n\n"
            f"Best regards,\nCopywriterflo Team"
        )

        html_body = f"""
        <div style="font-family: 'DM Sans', Arial, sans-serif; background:#07090f; padding:32px 16px;">
          <div style="max-width:480px;margin:0 auto;background:#11141f;border:1px solid #232840;border-radius:16px;overflow:hidden;">
            <div style="padding:28px 28px 8px;">
              <div style="font-family: 'Syne', Arial, sans-serif; font-weight:800; font-size:13px; color:#ff6a3d; letter-spacing:.03em;">COPYWRITERFLO</div>
              <h1 style="font-family: 'Syne', Arial, sans-serif; font-size:22px; color:#eceef4; margin:10px 0 4px;">Your payment details</h1>
              <p style="color:#8890a6; font-size:14px; line-height:1.6; margin:0 0 20px;">Hi {username}, here's everything you need to complete your lifetime access purchase.</p>
            </div>
            <div style="padding:0 28px;">
              <div style="text-align:center; margin-bottom:18px;">
                <img src="{qr_code}" alt="Payment QR code" width="180" height="180" style="border-radius:12px; background:#fff; padding:8px;">
              </div>
              <table style="width:100%; border-collapse:collapse; font-size:13.5px; color:#eceef4;">
                <tr>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; color:#8890a6;">Amount to send (exact)</td>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; text-align:right; font-weight:700; color:#ff6a3d;">{amount} {currency}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; color:#8890a6;">Order ID</td>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; text-align:right; font-family:monospace;">{order_id}</td>
                </tr>
              </table>
              <div style="margin:18px 0; padding:14px; background:#0b0e17; border:1px solid #232840; border-radius:10px; word-break:break-all; font-family:monospace; font-size:12.5px; color:#eceef4;">
                {address}
              </div>
              <p style="color:#f6a65e; font-size:12.5px; line-height:1.6; margin:0 0 4px;">⚠️ Send the exact amount above — it's how we automatically detect your payment.</p>
            </div>
            <div style="padding:8px 28px 28px;">
              <a href="{payment_url}" style="display:block; text-align:center; background:#ff6a3d; color:#0a0a0a; text-decoration:none; font-weight:700; padding:13px; border-radius:10px; font-size:14px;">View Payment Status</a>
              <p style="color:#565f78; font-size:12px; line-height:1.6; margin-top:16px;">Access unlocks automatically once your payment is detected on-chain — no confirmation step needed.</p>
            </div>
          </div>
        </div>
        """
        return text_body, html_body
    
    def _generate_unique_crypto_amount(self, crypto_currency):
        """Base USD price converted to the coin, plus a small random 'tag' in the last
        couple of decimals, so this order can be told apart from any other pending order
        on the same shared wallet address. Retries on the rare chance of a collision."""
        base_amount = usd_to_crypto(self.price_amount, crypto_currency)

        for _ in range(10):
            # Tag with 0.00000100 - 0.00999999 extra units. Small enough to be financially
            # negligible at this price point, large enough to be distinguishable from
            # blockchain rounding noise.
            tag = random.randint(100, 999999) / 1e8
            candidate = round(base_amount + tag, 8)
            if not self.db.crypto_amount_taken(crypto_currency, candidate):
                return candidate

        raise RuntimeError(f"Could not generate a unique payment amount for {crypto_currency}")

    def create_payment(self, user_id, user_email, crypto_currency='USDT', **kwargs):
        """Create a payment record with QR code"""
        if crypto_currency not in self.supported_currencies:
            return {
                'success': False,
                'error': f'Unsupported currency. Supported: {", ".join(self.supported_currencies)}'
            }
        
        address = self.get_address(crypto_currency)
        if not address:
            return {
                'success': False,
                'error': f'No wallet address configured for {crypto_currency}'
            }
        
        order_id = f"ORDER-{user_id}-{int(datetime.now().timestamp())}"
        
        try:
            crypto_amount = self._generate_unique_crypto_amount(crypto_currency)

            # Save payment to database
            payment_id = self.db.save_crypto_payment(
                user_id=user_id,
                order_id=order_id,
                provider_order_id=order_id,
                provider='direct',
                amount=self.price_amount,
                currency=self.price_currency,
                crypto_currency=crypto_currency,
                payment_url='',
                status='pending',
                crypto_amount=crypto_amount,
                pay_to_address=address,
                confirmations_required=get_confirmations_required(crypto_currency)
            )
            
            # Generate QR code — encodes the exact tagged amount the user must send
            qr_code = self.generate_qr_code(address, crypto_amount, crypto_currency)
            
            # Get user info
            user = self.db.get_user(user_id)
            user_username = user.get('username', 'User') if user else 'User'
            
            # Email the payment details to the user so they have them on hand
            payment_url = f"{self.app_url}/payment/{order_id}"
            text_body, html_body = self._build_payment_email(
                username=user_username,
                order_id=order_id,
                address=address,
                crypto_currency=crypto_currency,
                amount=crypto_amount,
                currency=crypto_currency,
                qr_code=qr_code,
                payment_url=payment_url
            )
            email_sent = self._send_email(
                user_email,
                f'💳 Your Payment Details — Order {order_id}',
                text_body,
                html_body
            )
            
            return {
                'success': True,
                'payment_id': payment_id,
                'order_id': order_id,
                'address': address,
                'qr_code': qr_code,
                'crypto_currency': crypto_currency,
                'crypto_amount': crypto_amount,
                'amount': self.price_amount,
                'currency': self.price_currency,
                'provider': 'direct',
                'email_sent': email_sent
            }
            
        except Exception as e:
            print(f"❌ Payment creation error: {e}")
            return {'success': False, 'error': str(e)}
    
    def mark_seen(self, order_id, tx_hash, confirmations):
        """Called by the background verifier when a matching tx is found but doesn't yet
        have enough confirmations. Lets the payment page show 'detected, confirming...'."""
        self.db.mark_crypto_payment_seen(order_id, tx_hash, confirmations)

    def auto_confirm_payment(self, order_id, tx_hash, confirmations):
        """Called ONLY by the background on-chain verifier once it has found a real
        transaction to this order's address matching its tagged amount with enough
        confirmations. Never trust a client-supplied transaction ID here — that was
        the old (insecure) flow."""
        payment = self.db.complete_crypto_payment(order_id, tx_hash, confirmations)

        if not payment:
            # Already completed by a previous poll, or the order doesn't exist —
            # either way there's nothing more to do.
            return {'success': False, 'error': 'Payment not pending (already completed or not found)'}

        # Grant lifetime access
        self.grant_lifetime_access(payment['user_id'], payment['id'])

        # Send confirmation emails
        user = self.db.get_user(payment['user_id'])
        if user:
            user_email = user.get('email')
            user_username = user.get('username', 'User')

            if user_email:
                self._send_email(
                    user_email,
                    '✅ Payment Confirmed - Copywriterflo Lifetime Access',
                    f'Hi {user_username},\n\nYour payment was detected on-chain and confirmed automatically! '
                    f'You now have lifetime access to Copywriterflo.\n\nOrder ID: {order_id}\n'
                    f'Transaction hash: {tx_hash}\n\nLogin here: {self.app_url}/dashboard\n\n'
                    f'Best regards,\nCopywriterflo Team'
                )

            if self.admin_email:
                self._send_email(
                    self.admin_email,
                    f'💰 New Payment: ${payment["amount"]} - {user_username}',
                    f'Payment auto-confirmed on-chain!\n\nUser: {user_username}\nEmail: {user_email}\n'
                    f'Amount: ${payment["amount"]} {payment["currency"]}\nCrypto: {payment["crypto_currency"]} '
                    f'{payment.get("crypto_amount")}\nOrder ID: {order_id}\nTx hash: {tx_hash}\n'
                    f'Confirmations: {confirmations}\n\nAccess granted automatically.'
                )

        return {'success': True, 'message': 'Payment confirmed automatically'}

    def get_payment_status(self, order_id):
        """Lightweight status for the payment page to poll — no sensitive data, just
        enough to show progress."""
        payment = self.db.get_crypto_payment_by_order_id(order_id)
        if not payment:
            return None
        return {
            'order_id': payment['order_id'],
            'status': payment['status'],
            'confirmations': payment.get('confirmations') or 0,
            'confirmations_required': payment.get('confirmations_required') or 1,
            'tx_hash': payment.get('tx_hash'),
        }

    def grant_lifetime_access(self, user_id, payment_id):
        self.db.grant_lifetime_access(user_id, payment_id)
    
    def user_has_lifetime_access(self, user_id):
        return self.db.user_has_lifetime_access(user_id)
    
    def get_payment_info(self, user_id):
        return self.db.get_user_payment_info(user_id)

# Initialize singleton
crypto_payment = CryptoPayment()