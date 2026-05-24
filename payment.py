# payment.py
import stripe
import os
from datetime import datetime
from database import Database
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
CAMPAIGN_PRICE = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 28000))
CURRENCY = os.environ.get('CURRENCY', 'usd')

db = Database()

def create_payment_session(user_id, email, success_url, cancel_url):
    """Create a Stripe checkout session for lifetime access"""
    try:
        if not stripe.api_key:
            error_msg = "Stripe API key not configured. Please add STRIPE_SECRET_KEY to .env file"
            print(f"❌ {error_msg}")
            return None, None
        
        print(f"💰 Creating Stripe checkout session...")
        print(f"   Amount: {CAMPAIGN_PRICE} ({CURRENCY})")
        print(f"   Email: {email}")
        
        session = stripe.checkout.Session.create(
            customer_email=email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': CURRENCY.lower(),
                    'product_data': {
                        'name': 'Copywriterflo - Lifetime Access',
                        'description': 'One-time payment for lifetime access to unlimited campaigns, AI lead scoring, email automation, business search, and all future features.',
                    },
                    'unit_amount': CAMPAIGN_PRICE,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'user_id': str(user_id),
                'type': 'lifetime_access'
            }
        )
        print(f"✅ Stripe checkout session created: {session.id}")
        print(f"   Checkout URL: {session.url}")
        return session.id, session.url
    except stripe.error.AuthenticationError as e:
        print(f"❌ Stripe Authentication Error: {e}")
        print("   Please check your STRIPE_SECRET_KEY in .env file")
        return None, None
    except stripe.error.InvalidRequestError as e:
        print(f"❌ Stripe Invalid Request Error: {e}")
        return None, None
    except Exception as e:
        print(f"❌ Error creating Stripe session: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def handle_successful_payment(session_id):
    """Handle successful payment and grant lifetime access"""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        metadata = session.metadata
        
        user_id = int(metadata.get('user_id'))
        
        if session.payment_status == 'paid':
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if payment already recorded - using db.use_postgres flag
                if db.use_postgres:
                    cursor.execute('SELECT id FROM payments WHERE stripe_session_id = %s', (session_id,))
                    existing = cursor.fetchone()
                else:
                    cursor.execute('SELECT id FROM payments WHERE stripe_session_id = ?', (session_id,))
                    existing = cursor.fetchone()
                
                if existing:
                    print(f"Payment {session_id} already recorded")
                    return True
                
                # Record the payment
                if db.use_postgres:
                    cursor.execute('''
                        INSERT INTO payments 
                        (user_id, stripe_session_id, amount, currency, payment_date)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id
                    ''', (user_id, session_id, CAMPAIGN_PRICE, CURRENCY, datetime.now().isoformat()))
                    payment_id = cursor.fetchone()['id']
                    
                    # Grant lifetime access
                    cursor.execute('''
                        INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at, payment_id)
                        VALUES (%s, 1, %s, %s)
                        ON CONFLICT(user_id) DO UPDATE SET
                            has_lifetime_access = 1,
                            access_granted_at = %s,
                            payment_id = %s
                    ''', (user_id, datetime.now().isoformat(), payment_id,
                          datetime.now().isoformat(), payment_id))
                else:
                    cursor.execute('''
                        INSERT INTO payments 
                        (user_id, stripe_session_id, amount, currency, payment_date)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, session_id, CAMPAIGN_PRICE, CURRENCY, datetime.now().isoformat()))
                    payment_id = cursor.lastrowid
                    
                    # Grant lifetime access
                    cursor.execute('''
                        INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at, payment_id)
                        VALUES (?, 1, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            has_lifetime_access = 1,
                            access_granted_at = ?,
                            payment_id = ?
                    ''', (user_id, datetime.now().isoformat(), payment_id,
                          datetime.now().isoformat(), payment_id))
                
            print(f"✅ Payment recorded and lifetime access granted to user {user_id}")
            return True
    except Exception as e:
        print(f"Error handling payment: {e}")
        import traceback
        traceback.print_exc()
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