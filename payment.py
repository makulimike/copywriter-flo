# payment.py - Grey payment integration
import os
import hashlib
import hmac
from datetime import datetime
from database import Database
from dotenv import load_dotenv

load_dotenv()

# Grey configuration
GREY_API_KEY = os.environ.get('GREY_API_KEY')
GREY_ACCOUNT_ID = os.environ.get('GREY_ACCOUNT_ID')
GREY_WEBHOOK_SECRET = os.environ.get('GREY_WEBHOOK_SECRET', 'your-webhook-secret-here-change-this')

CAMPAIGN_PRICE = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 280))  # $280 USD
CURRENCY = os.environ.get('CURRENCY', 'USD')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5000')

db = Database()


def get_grey_bank_details():
    """Get your Grey bank account details for receiving payments"""
    return {
        'bank_name': os.environ.get('GREY_BANK_NAME', 'Grey'),
        'account_name': os.environ.get('GREY_ACCOUNT_NAME', 'Your Business Name'),
        'account_number': os.environ.get('GREY_ACCOUNT_NUMBER', ''),
        'routing_number': os.environ.get('GREY_ROUTING_NUMBER', ''),
        'iban': os.environ.get('GREY_IBAN', ''),
        'swift_bic': os.environ.get('GREY_SWIFT_BIC', ''),
        'currency': CURRENCY,
        'reference_instructions': "Use your unique reference code when sending payment"
    }


def get_user_grey_payment_details(user_id, user_email):
    """Generate unique payment reference for a user"""
    timestamp = int(datetime.now().timestamp())
    reference = f"COPYWRITER-{user_id}-{timestamp}"
    
    # Store pending payment in database
    with db.get_connection() as conn:
        cursor = conn.cursor()
        if db.use_postgres:
            cursor.execute('''
                INSERT INTO grey_payments (user_id, reference, amount, currency, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            ''', (user_id, reference, CAMPAIGN_PRICE, CURRENCY, 'pending', datetime.now().isoformat()))
            payment_id = cursor.fetchone()['id']
        else:
            cursor.execute('''
                INSERT INTO grey_payments (user_id, reference, amount, currency, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, reference, CAMPAIGN_PRICE, CURRENCY, 'pending', datetime.now().isoformat()))
            payment_id = cursor.lastrowid
    
    return {
        'reference': reference,
        'payment_id': payment_id,
        'amount': CAMPAIGN_PRICE,
        'currency': CURRENCY,
        'bank_details': get_grey_bank_details()
    }


def verify_grey_webhook_signature(request_body, signature_header):
    """Verify that the webhook came from Grey"""
    expected_signature = hmac.new(
        GREY_WEBHOOK_SECRET.encode('utf-8'),
        request_body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)


def handle_grey_webhook(data):
    """Process incoming Grey webhook for payment confirmation"""
    event_type = data.get('event')
    payment_data = data.get('data', {})
    
    if event_type == 'payment.received':
        reference = payment_data.get('reference', '')
        amount = payment_data.get('amount')
        currency = payment_data.get('currency')
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if db.use_postgres:
                cursor.execute('''
                    SELECT id, user_id, status FROM grey_payments 
                    WHERE reference = %s AND amount = %s AND currency = %s
                ''', (reference, amount, currency))
                payment = cursor.fetchone()
                
                if payment and payment['status'] == 'pending':
                    cursor.execute('''
                        UPDATE grey_payments 
                        SET status = 'completed', completed_at = %s, transaction_id = %s
                        WHERE id = %s
                    ''', (datetime.now().isoformat(), payment_data.get('transaction_id'), payment['id']))
                    
                    grant_lifetime_access(payment['user_id'], payment['id'])
                    return True
            else:
                cursor.execute('''
                    SELECT id, user_id, status FROM grey_payments 
                    WHERE reference = ? AND amount = ? AND currency = ?
                ''', (reference, amount, currency))
                payment = cursor.fetchone()
                
                if payment and payment[2] == 'pending':
                    cursor.execute('''
                        UPDATE grey_payments 
                        SET status = 'completed', completed_at = ?, transaction_id = ?
                        WHERE id = ?
                    ''', (datetime.now().isoformat(), payment_data.get('transaction_id'), payment[0]))
                    
                    grant_lifetime_access(payment[1], payment[0])
                    return True
    
    return False


def grant_lifetime_access(user_id, payment_id):
    """Grant lifetime access to user after payment confirmation"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        if db.use_postgres:
            cursor.execute('''
                INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at, payment_id)
                VALUES (%s, 1, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    has_lifetime_access = 1,
                    access_granted_at = %s,
                    payment_id = %s
            ''', (user_id, datetime.now().isoformat(), payment_id, datetime.now().isoformat(), payment_id))
        else:
            cursor.execute('''
                INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at, payment_id)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    has_lifetime_access = 1,
                    access_granted_at = ?,
                    payment_id = ?
            ''', (user_id, datetime.now().isoformat(), payment_id, datetime.now().isoformat(), payment_id))


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
                           gp.amount, gp.currency, gp.completed_at, gp.reference, gp.status
                    FROM user_access ua
                    LEFT JOIN grey_payments gp ON ua.payment_id = gp.id
                    WHERE ua.user_id = %s
                    ORDER BY gp.created_at DESC
                    LIMIT 1
                ''', (user_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'has_access': result['has_lifetime_access'] == 1,
                        'granted_at': result['access_granted_at'],
                        'amount': result['amount'],
                        'currency': result['currency'],
                        'payment_date': result['completed_at'],
                        'reference': result['reference'],
                        'status': result['status']
                    }
            else:
                cursor.execute('''
                    SELECT ua.has_lifetime_access, ua.access_granted_at, 
                           gp.amount, gp.currency, gp.completed_at, gp.reference, gp.status
                    FROM user_access ua
                    LEFT JOIN grey_payments gp ON ua.payment_id = gp.id
                    WHERE ua.user_id = ?
                    ORDER BY gp.created_at DESC
                    LIMIT 1
                ''', (user_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'has_access': result[0] == 1,
                        'granted_at': result[1],
                        'amount': result[2],
                        'currency': result[3],
                        'payment_date': result[4],
                        'reference': result[5],
                        'status': result[6]
                    }
            return {'has_access': False, 'status': None}
    except Exception as e:
        print(f"Error getting payment status: {e}")
        return {'has_access': False, 'status': None}