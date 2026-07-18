# payments_intersend.py - IntaSend Payment Integration (Production Ready)

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import uuid
import requests
import json
from database import Database

db = Database()

class IntersendPayment:
    def __init__(self):
        # Get environment from .env (default to live for production)
        self.environment = os.environ.get('INTERSEND_ENVIRONMENT', 'live')
        
        # Set API URL based on environment
        if self.environment == 'sandbox':
            self.api_url = 'https://sandbox.intasend.com/'
        else:
            self.api_url = 'https://api.intasend.com/'
        
        # API Keys
        self.publishable_key = os.environ.get('INTERSEND_PUBLISHABLE_KEY')
        self.secret_key = os.environ.get('INTERSEND_SECRET_KEY')
        self.webhook_secret = os.environ.get('INTERSEND_WEBHOOK_SECRET')
        
        self.app_url = os.environ.get('APP_URL', 'http://localhost:5000')
        self.price_amount = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 280))
        self.price_currency = os.environ.get('CURRENCY', 'USD')
        self.intersend_enabled = os.environ.get('INTERSEND_ENABLED', 'True').lower() == 'true'
        
        # Email settings
        self.smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER', '')
        self.smtp_password = os.environ.get('SMTP_PASSWORD', '')
        self.from_email = os.environ.get('SMTP_USER', '')
        self.admin_email = os.environ.get('ADMIN_EMAIL', '')
        
        self.db = db
        
        # Supported currencies - FIAT only
        self.supported_currencies = ['USD', 'EUR', 'GBP', 'NGN', 'KES', 'ZAR']
        
        # Currency symbols for display
        self.currency_symbols = {
            'USD': '$', 'EUR': '€', 'GBP': '£',
            'NGN': '₦', 'KES': 'KSh', 'ZAR': 'R'
        }
        
        # Currency flags for display
        self.currency_flags = {
            'USD': '🇺🇸', 'EUR': '🇪🇺', 'GBP': '🇬🇧',
            'NGN': '🇳🇬', 'KES': '🇰🇪', 'ZAR': '🇿🇦'
        }
        
        # Startup banner
        self._print_banner()
    
    def _print_banner(self):
        """Print startup banner"""
        configured = self.secret_key is not None and self.secret_key != ''
        print("=" * 60)
        print("💳 INTA SEND PAYMENT INTEGRATION")
        print("=" * 60)
        print(f"🌍 Environment: {self.environment.upper()}")
        print(f"🔗 API URL: {self.api_url}")
        print(f"✅ Enabled: {self.intersend_enabled}")
        print(f"✅ Configured: {configured}")
        if configured:
            print(f"🔑 Secret Key: {self.secret_key[:20]}...")
            print(f"💰 Supported currencies: {', '.join(self.supported_currencies)}")
            print(f"💵 Price: {self.currency_symbols.get(self.price_currency, '$')}{self.price_amount} {self.price_currency}")
            if self.environment == 'sandbox':
                print("🧪 SANDBOX MODE - Test cards: 4111111111111111 (Visa)")
            else:
                print("🔒 LIVE MODE - Real payments")
        else:
            print("⚠️ INTERSEND_SECRET_KEY not set in .env")
        print("=" * 60)
    
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
                server = smtplib.SMTP(self.smtp_host, int(self.smtp_port))
                server.starttls()
            
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email sent to {to_email}")
            return True
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
            return False
    
    def _make_request(self, method, endpoint, data=None):
        """
        Make authenticated request to IntaSend API
        Uses the correct Bearer token authentication
        """
        if not self.secret_key:
            return {'success': False, 'error': 'Secret key not configured'}
        
        # Ensure URL has correct format
        base_url = self.api_url.rstrip('/')
        endpoint = endpoint.lstrip('/')
        url = f"{base_url}/{endpoint}"
        
        # Correct authentication headers
        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        print(f"📡 {method} → {url}")
        if data:
            safe_data = {k: v for k, v in data.items() if k not in ['email', 'first_name', 'last_name']}
            print(f"📤 Payload: {json.dumps(safe_data, indent=2)[:500]}...")
        
        try:
            if method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            else:
                return {'success': False, 'error': f'Unsupported method: {method}'}
            
            print(f"📥 Status: {response.status_code}")
            
            # Try to parse JSON response
            try:
                result = response.json()
                if response.status_code >= 400:
                    error_msg = result.get('message') or result.get('error') or result.get('detail') or str(response.status_code)
                    print(f"❌ Error: {error_msg}")
                    if response.status_code == 401:
                        print("🔑 Authentication failed - please verify your API key is correct and active")
                        print("💡 If using sandbox, ensure you're using keys from: https://sandbox.intasend.com/account/api-keys/")
                        print("💡 If using live, ensure you're using keys from: https://payment.intasend.com/account/api-keys/")
                    return {'success': False, 'error': error_msg, 'data': result}
                print(f"✅ Request successful")
                return {'success': True, 'data': result}
            except ValueError:
                if response.status_code >= 400:
                    error_msg = f'HTTP {response.status_code}: {response.text[:200]}'
                    print(f"❌ Error: {error_msg}")
                    return {'success': False, 'error': error_msg}
                
                response.raise_for_status()
                return {'success': True, 'data': response.text}
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            print(f"❌ Request error: {error_msg}")
            return {'success': False, 'error': error_msg}
    
    def create_payment(self, user_id, user_email, currency='USD', **kwargs):
        """
        Create an IntaSend payment for card processing
        """
        if not self.intersend_enabled:
            return {'success': False, 'error': 'Payments are disabled'}
        
        if currency not in self.supported_currencies:
            return {
                'success': False,
                'error': f'Unsupported currency. Supported: {", ".join(self.supported_currencies)}'
            }
        
        if not self.secret_key:
            return {'success': False, 'error': 'IntaSend API not configured'}
        
        # Create order ID
        order_id = f"ORDER-{user_id}-{int(datetime.now().timestamp())}"
        
        # Get user info
        user = self.db.get_user(user_id)
        user_username = user.get('username', 'User') if user else 'User'
        
        # Split name into first and last name
        name_parts = user_username.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Prepare payment data - Matches the curl example
        payment_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': user_email,
            'method': 'CARD-PAYMENT',
            'amount': self.price_amount,
            'currency': currency,
            'order_id': order_id,
            'redirect_url': f"{self.app_url}/payment/intersend/{order_id}/callback",
            'webhook_url': f"{self.app_url}/webhook/intersend",
        }
        
        # Correct endpoint - matches the curl example
        endpoint = 'api/v1/checkout/'
        print(f"🔄 Trying endpoint: {endpoint}")
        response = self._make_request('POST', endpoint, payment_data)
        
        if not response['success']:
            return {
                'success': False, 
                'error': response.get('error', 'Failed to create payment')
            }
        
        data = response['data']
        print(f"📦 Response: {json.dumps(data, indent=2)[:500]}...")
        
        # Extract checkout URL from the response
        checkout_url = None
        if isinstance(data, dict):
            if 'checkout_url' in data:
                checkout_url = data['checkout_url']
            elif 'url' in data:
                checkout_url = data['url']
            elif 'redirect_url' in data:
                checkout_url = data['redirect_url']
            elif 'payment_link' in data:
                checkout_url = data['payment_link']
            elif 'data' in data and isinstance(data['data'], dict):
                checkout_url = data['data'].get('checkout_url') or data['data'].get('url')
        
        # Get provider payment ID
        provider_payment_id = None
        if isinstance(data, dict):
            provider_payment_id = data.get('id') or data.get('payment_id') or data.get('transaction_id') or order_id
        
        # Save payment to database
        payment_id = self.db.save_intersend_payment(
            user_id=user_id,
            order_id=order_id,
            provider_payment_id=provider_payment_id,
            amount=self.price_amount,
            currency=currency,
            status='pending',
            checkout_url=checkout_url,
            payment_method='card'
        )
        
        # Send confirmation email
        if checkout_url:
            self._send_payment_email(user_email, user_username, order_id, checkout_url, currency)
        else:
            self._send_payment_email_no_checkout(user_email, user_username, order_id, currency)
        
        return {
            'success': True,
            'payment_id': payment_id,
            'order_id': order_id,
            'checkout_url': checkout_url,
            'provider_payment_id': provider_payment_id,
            'amount': self.price_amount,
            'currency': currency,
            'provider': 'intasend',
            'environment': self.environment
        }
    
    def _send_payment_email(self, user_email, username, order_id, checkout_url, currency):
        """Send payment instructions email with checkout link"""
        symbol = self.currency_symbols.get(currency, '$')
        env_label = "🧪 TEST" if self.environment == 'sandbox' else "🔒 LIVE"
        
        body = f"""Hi {username},

Your payment for Copywriterflo Lifetime Access is ready!

{env_label}
💳 Amount: {symbol}{self.price_amount} {currency}
📋 Order ID: {order_id}

🔗 Click here to complete your payment:
{checkout_url}

This is a one-time payment for lifetime access. No recurring charges.

Best regards,
Copywriterflo Team
"""
        
        html_body = f"""
        <div style="font-family: 'DM Sans', Arial, sans-serif; background:#07090f; padding:32px 16px;">
          <div style="max-width:480px;margin:0 auto;background:#11141f;border:1px solid #232840;border-radius:16px;overflow:hidden;">
            <div style="padding:28px 28px 8px;">
              <div style="font-family: 'Syne', Arial, sans-serif; font-weight:800; font-size:13px; color:#ff6a3d; letter-spacing:.03em;">COPYWRITERFLO</div>
              <h1 style="font-family: 'Syne', Arial, sans-serif; font-size:22px; color:#eceef4; margin:10px 0 4px;">Complete your payment</h1>
              <p style="color:#8890a6; font-size:14px; line-height:1.6; margin:0 0 20px;">Hi {username}, click the button below to complete your lifetime access purchase.</p>
              <p style="color:#f6a65e; font-size:12px; line-height:1.6; margin:0 0 16px;">{env_label} Environment</p>
            </div>
            <div style="padding:0 28px;">
              <table style="width:100%; border-collapse:collapse; font-size:13.5px; color:#eceef4;">
                <tr>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; color:#8890a6;">Amount</td>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; text-align:right; font-weight:700; color:#ff6a3d;">{symbol}{self.price_amount} {currency}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; color:#8890a6;">Type</td>
                  <td style="padding:10px 0; border-bottom:1px solid #1a1e30; text-align:right; font-weight:700;">One-time payment</td>
                </tr>
                <tr>
                  <td style="padding:10px 0; color:#8890a6;">Order ID</td>
                  <td style="padding:10px 0; text-align:right; font-family:monospace; color:#eceef4;">{order_id}</td>
                </tr>
              </table>
            </div>
            <div style="padding:8px 28px 28px;">
              <a href="{checkout_url}" style="display:block; text-align:center; background:#ff6a3d; color:#0a0a0a; text-decoration:none; font-weight:700; padding:13px; border-radius:10px; font-size:14px;">💳 Pay with Card</a>
              <p style="color:#565f78; font-size:12px; line-height:1.6; margin-top:16px;">You'll be redirected to the secure payment page to enter your card details.</p>
              <p style="color:#565f78; font-size:11px; line-height:1.6; margin-top:8px;">🔒 Your payment is secure and encrypted. We never store your card details.</p>
            </div>
          </div>
        </div>
        """
        
        self._send_email(user_email, f'💳 Complete Your Payment — Order {order_id}', body, html_body)
    
    def _send_payment_email_no_checkout(self, user_email, username, order_id, currency):
        """Send payment instructions email without checkout link"""
        symbol = self.currency_symbols.get(currency, '$')
        env_label = "🧪 TEST" if self.environment == 'sandbox' else "🔒 LIVE"
        
        body = f"""Hi {username},

Your payment request for Copywriterflo Lifetime Access has been created.

{env_label}
💰 Amount: {symbol}{self.price_amount} {currency}
📋 Order ID: {order_id}

Please check your IntaSend dashboard to complete the payment.

This is a one-time payment for lifetime access.

Best regards,
Copywriterflo Team
"""
        
        self._send_email(
            user_email, 
            f'💳 Payment Created — Order {order_id}', 
            body
        )
    
    def confirm_payment(self, provider_payment_id, status, transaction_id=None):
        """Confirm payment status from webhook/callback"""
        payment = self.db.get_intersend_payment_by_provider_id(provider_payment_id)
        
        if not payment:
            return {'success': False, 'error': 'Payment not found'}
        
        if payment['status'] == 'completed':
            return {'success': True, 'message': 'Already completed'}
        
        if status in ['completed', 'success', 'paid']:
            # Complete the payment
            self.db.complete_intersend_payment(provider_payment_id, transaction_id)
            
            # Grant lifetime access
            self.db.grant_lifetime_access(payment['user_id'], payment['id'])
            
            # Send confirmation email
            user = self.db.get_user(payment['user_id'])
            if user:
                user_email = user.get('email')
                user_username = user.get('username', 'User')
                
                if user_email:
                    self._send_email(
                        user_email,
                        '✅ Payment Confirmed - Copywriterflo Lifetime Access',
                        f'Hi {user_username},\n\nYour payment has been confirmed! '
                        f'You now have lifetime access to Copywriterflo.\n\n'
                        f'Order ID: {payment["order_id"]}\n'
                        f'Transaction ID: {transaction_id or "N/A"}\n\n'
                        f'Login here: {self.app_url}/dashboard\n\n'
                        f'Best regards,\nCopywriterflo Team'
                    )
                
                if self.admin_email:
                    symbol = self.currency_symbols.get(payment['currency'], '$')
                    self._send_email(
                        self.admin_email,
                        f'💰 New Payment: {symbol}{payment["amount"]} - {user_username}',
                        f'✅ Payment confirmed!\n\n'
                        f'User: {user_username}\n'
                        f'Email: {user_email}\n'
                        f'Amount: {symbol}{payment["amount"]} {payment["currency"]}\n'
                        f'Order ID: {payment["order_id"]}\n'
                        f'Transaction ID: {transaction_id or "N/A"}\n\n'
                        f'Access granted automatically.'
                    )
            
            return {'success': True, 'message': 'Payment confirmed'}
        elif status in ['failed', 'cancelled', 'declined', 'expired']:
            self.db.update_intersend_payment_status(provider_payment_id, status)
            return {'success': True, 'message': f'Payment {status}'}
        
        # For 'pending' or other statuses, just update
        self.db.update_intersend_payment_status(provider_payment_id, status)
        return {'success': True, 'message': f'Status updated to {status}'}
    
    def get_payment_status(self, order_id):
        """Get payment status for polling"""
        payment = self.db.get_intersend_payment_by_order_id(order_id)
        if not payment:
            return None
        
        return {
            'order_id': payment['order_id'],
            'status': payment['status'],
            'amount': payment['amount'],
            'currency': payment['currency'],
            'created_at': payment['created_at'],
            'completed_at': payment.get('completed_at'),
            'provider_payment_id': payment.get('provider_payment_id'),
            'checkout_url': payment.get('checkout_url'),
        }
    
    def user_has_lifetime_access(self, user_id):
        return self.db.user_has_lifetime_access(user_id)
    
    def get_payment_info(self, user_id):
        return self.db.get_user_payment_info(user_id)

# Initialize singleton
intersend_payment = IntersendPayment()