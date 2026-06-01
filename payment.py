# payment.py
import paypalrestsdk
import os
from datetime import datetime
from database import Database
from dotenv import load_dotenv

load_dotenv()

# Configure PayPal
paypalrestsdk.configure({
    "mode": os.environ.get('PAYPAL_MODE', 'sandbox'),
    "client_id": os.environ.get('PAYPAL_CLIENT_ID'),
    "client_secret": os.environ.get('PAYPAL_CLIENT_SECRET')
})

CAMPAIGN_PRICE = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 28000)) / 100  # Convert to dollars
CURRENCY = os.environ.get('CURRENCY', 'USD')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5000')

db = Database()

def create_paypal_payment(user_id, email, return_url, cancel_url):
    """Create a PayPal payment for lifetime access"""
    try:
        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {
                "payment_method": "paypal"
            },
            "redirect_urls": {
                "return_url": return_url,
                "cancel_url": cancel_url
            },
            "transactions": [{
                "item_list": {
                    "items": [{
                        "name": "Copywriterflo - Lifetime Access",
                        "sku": "LIFETIME-001",
                        "price": str(CAMPAIGN_PRICE),
                        "currency": CURRENCY,
                        "quantity": 1
                    }]
                },
                "amount": {
                    "currency": CURRENCY,
                    "total": str(CAMPAIGN_PRICE)
                },
                "description": "One-time payment for lifetime access to unlimited campaigns, AI lead scoring, email automation, business search, and all future features."
            }],
            "note_to_payer": "Thank you for your purchase! You will get lifetime access to Copywriterflo."
        })

        if payment.create():
            print(f"✅ PayPal payment created: {payment.id}")
            
            # Store payment info in database
            with db.get_connection() as conn:
                cursor = conn.cursor()
                if db.use_postgres:
                    cursor.execute('''
                        INSERT INTO payments (user_id, paypal_payment_id, amount, currency, status, payment_date)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (user_id, payment.id, int(CAMPAIGN_PRICE * 100), CURRENCY, 'pending', datetime.now().isoformat()))
                else:
                    cursor.execute('''
                        INSERT INTO payments (user_id, paypal_payment_id, amount, currency, status, payment_date)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (user_id, payment.id, int(CAMPAIGN_PRICE * 100), CURRENCY, 'pending', datetime.now().isoformat()))
            
            # Get approval URL
            for link in payment.links:
                if link.rel == "approval_url":
                    return payment.id, link.href
            
            return payment.id, None
        else:
            print(f"❌ PayPal payment creation failed: {payment.error}")
            return None, None
            
    except Exception as e:
        print(f"❌ Error creating PayPal payment: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def execute_paypal_payment(payment_id, payer_id):
    """Execute a PayPal payment after user approval"""
    try:
        payment = paypalrestsdk.Payment.find(payment_id)
        
        if payment.execute({"payer_id": payer_id}):
            print(f"✅ PayPal payment executed: {payment_id}")
            
            # Get user_id from database
            with db.get_connection() as conn:
                cursor = conn.cursor()
                if db.use_postgres:
                    cursor.execute('SELECT user_id FROM payments WHERE paypal_payment_id = %s', (payment_id,))
                    result = cursor.fetchone()
                    
                    if result:
                        user_id = result['user_id']
                        
                        # Update payment status
                        cursor.execute('''
                            UPDATE payments SET status = 'completed' WHERE paypal_payment_id = %s
                        ''', (payment_id,))
                        
                        # Grant lifetime access
                        cursor.execute('''
                            INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at)
                            VALUES (%s, 1, %s)
                            ON CONFLICT(user_id) DO UPDATE SET
                                has_lifetime_access = 1,
                                access_granted_at = %s
                        ''', (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
                        
                        return True
                else:
                    cursor.execute('SELECT user_id FROM payments WHERE paypal_payment_id = ?', (payment_id,))
                    result = cursor.fetchone()
                    
                    if result:
                        user_id = result[0]
                        
                        # Update payment status
                        cursor.execute('''
                            UPDATE payments SET status = 'completed' WHERE paypal_payment_id = ?
                        ''', (payment_id,))
                        
                        # Grant lifetime access
                        cursor.execute('''
                            INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at)
                            VALUES (?, 1, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                                has_lifetime_access = 1,
                                access_granted_at = ?
                        ''', (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
                        
                        return True
            return False
        else:
            print(f"❌ PayPal payment execution failed: {payment.error}")
            return False
    except Exception as e:
        print(f"❌ Error executing PayPal payment: {e}")
        return False

def user_has_lifetime_access(user_id):
    """Check if user has paid for lifetime access"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if db.use_postgres:
                cursor.execute('SELECT has_lifetime_access FROM user_access WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
                if result:
                    return result['has_lifetime_access'] == 1
            else:
                cursor.execute('SELECT has_lifetime_access FROM user_access WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                if result:
                    return result[0] == 1
            return False
    except Exception as e:
        print(f"Error checking lifetime access: {e}")
        return False

def get_payment_status(user_id):
    """Get detailed payment status for user"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if db.use_postgres:
                cursor.execute('''
                    SELECT ua.has_lifetime_access, ua.access_granted_at, 
                           p.amount, p.currency, p.payment_date
                    FROM user_access ua
                    LEFT JOIN payments p ON ua.payment_id = p.id
                    WHERE ua.user_id = %s
                ''', (user_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'has_access': result['has_lifetime_access'] == 1,
                        'granted_at': result['access_granted_at'],
                        'amount': result['amount'],
                        'currency': result['currency'],
                        'payment_date': result['payment_date']
                    }
            else:
                cursor.execute('''
                    SELECT ua.has_lifetime_access, ua.access_granted_at, 
                           p.amount, p.currency, p.payment_date
                    FROM user_access ua
                    LEFT JOIN payments p ON ua.payment_id = p.id
                    WHERE ua.user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'has_access': result[0] == 1,
                        'granted_at': result[1],
                        'amount': result[2],
                        'currency': result[3],
                        'payment_date': result[4]
                    }
            return {'has_access': False}
    except Exception as e:
        print(f"Error getting payment status: {e}")
        return {'has_access': False}