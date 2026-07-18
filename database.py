# database.py - PostgreSQL Only (Updated with Trial Fields)

import os
from datetime import datetime, timedelta
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load .env file as fallback for Render
load_dotenv()

class Database:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            # Try loading from .env as fallback
            load_dotenv()
            self.database_url = os.environ.get('DATABASE_URL')
            if not self.database_url:
                raise ValueError("DATABASE_URL environment variable is required. Set it in .env file or Render environment variables")
        
        print("✅ Using PostgreSQL database")
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        """Get PostgreSQL connection with RealDictCursor"""
        conn = psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _row_to_dict(self, row):
        """Convert database row to dictionary"""
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
        return dict(row)
    
    def init_db(self):
        """Initialize all tables for PostgreSQL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table with trial fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    whatsapp_number TEXT,
                    telegram_chat_id TEXT,
                    meeting_link TEXT,
                    trial_started_at TIMESTAMP,
                    trial_ended_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL
                )
            ''')
            
            # API Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_settings (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    openai_model TEXT DEFAULT 'gpt-3.5-turbo',
                    smtp_host TEXT DEFAULT 'smtp.gmail.com',
                    smtp_port INTEGER DEFAULT 587,
                    smtp_user TEXT,
                    smtp_password TEXT,
                    auto_send_enabled INTEGER DEFAULT 0,
                    auto_send_score INTEGER DEFAULT 7,
                    meeting_link TEXT,
                    google_meet_enabled INTEGER DEFAULT 0,
                    updated_at TIMESTAMP
                )
            ''')
            
            # Campaigns table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    industry TEXT,
                    script TEXT,
                    default_location TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP NOT NULL
                )
            ''')
            
            # Leads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
                    name TEXT NOT NULL,
                    email TEXT,
                    company TEXT,
                    website TEXT,
                    phone TEXT,
                    address TEXT,
                    rating REAL DEFAULT 0,
                    total_ratings INTEGER DEFAULT 0,
                    place_id TEXT,
                    status TEXT DEFAULT 'pending',
                    score INTEGER DEFAULT 0,
                    score_reason TEXT,
                    personalized_message TEXT,
                    email_sent INTEGER DEFAULT 0,
                    email_sent_at TIMESTAMP,
                    opened INTEGER DEFAULT 0,
                    replied INTEGER DEFAULT 0,
                    meeting_scheduled INTEGER DEFAULT 0,
                    meeting_link TEXT,
                    meeting_time TIMESTAMP,
                    confirmation_token TEXT,
                    confirmation_sent_at TIMESTAMP,
                    website_analyzed INTEGER DEFAULT 0,
                    website_analysis TEXT,
                    website_issues TEXT,
                    website_recommendations TEXT,
                    created_at TIMESTAMP NOT NULL
                )
            ''')
            
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER NOT NULL REFERENCES leads(id),
                    subject TEXT,
                    content TEXT,
                    sent_at TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    opened_at TIMESTAMP,
                    replied_at TIMESTAMP,
                    error_message TEXT
                )
            ''')
            
            # Notifications table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    email_enabled INTEGER DEFAULT 1,
                    sms_enabled INTEGER DEFAULT 0,
                    whatsapp_enabled INTEGER DEFAULT 0,
                    telegram_enabled INTEGER DEFAULT 0
                )
            ''')
            
            # Business searches table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS business_searches (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
                    keyword TEXT NOT NULL,
                    location TEXT,
                    total_results INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'openstreetmap',
                    created_at TIMESTAMP NOT NULL
                )
            ''')
            
            # Intersend payments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS intersend_payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    order_id TEXT UNIQUE NOT NULL,
                    provider_payment_id TEXT,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    checkout_url TEXT,
                    payment_method TEXT DEFAULT 'card',
                    transaction_id TEXT,
                    created_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_campaigns_user ON campaigns(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_intersend_payments_user ON intersend_payments(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_intersend_payments_status ON intersend_payments(status)')
            
            # User access table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_access (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    has_lifetime_access INTEGER DEFAULT 0,
                    access_granted_at TIMESTAMP,
                    payment_id INTEGER REFERENCES intersend_payments(id)
                )
            ''')
            
            print("✅ Database tables created/verified")
    
    # ============================================
    # USER METHODS (Updated with Trial)
    # ============================================
    
    def create_user(self, username, password, email, phone="", whatsapp_number=""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            trial_days = int(os.environ.get('TRIAL_DAYS', 3))
            trial_end = now + timedelta(days=trial_days)
            
            cursor.execute('''
                INSERT INTO users (username, password, email, phone, whatsapp_number, 
                                   trial_started_at, trial_ended_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''', (username, password, email, phone, whatsapp_number, now, trial_end, now))
            user_id = cursor.fetchone()['id']
            
            cursor.execute('''
                INSERT INTO notifications (user_id, email_enabled)
                VALUES (%s, 1) ON CONFLICT (user_id) DO NOTHING
            ''', (user_id,))
            cursor.execute('''
                INSERT INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                VALUES (%s, 0, 7, 0, %s) ON CONFLICT (user_id) DO NOTHING
            ''', (user_id, now))
            return user_id
    
    def get_user_by_username(self, username):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def get_user_trial_status(self, user_id):
        """Get trial status for a user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT trial_started_at, trial_ended_at, created_at 
                FROM users WHERE id = %s
            ''', (user_id,))
            result = cursor.fetchone()
            if result:
                return self._row_to_dict(result)
            return None
    
    def is_trial_active(self, user_id):
        """Check if user's trial is still active"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT trial_ended_at FROM users WHERE id = %s
            ''', (user_id,))
            result = cursor.fetchone()
            if result and result['trial_ended_at']:
                return datetime.now() < result['trial_ended_at']
            return False
    
    def extend_trial(self, user_id, days=3):
        """Extend trial by specified days"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            new_end = datetime.now() + timedelta(days=days)
            cursor.execute('''
                UPDATE users SET trial_ended_at = %s WHERE id = %s
            ''', (new_end, user_id))
    
    # ============================================
    # API SETTINGS METHODS
    # ============================================
    
    def get_api_settings(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM api_settings WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            if not result:
                cursor.execute('''
                    INSERT INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                    VALUES (%s, 0, 7, 0, %s) ON CONFLICT (user_id) DO NOTHING
                ''', (user_id, datetime.now()))
                cursor.execute('SELECT * FROM api_settings WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_api_settings(self, user_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = %s")
                values.append(value)
            values.append(datetime.now())
            values.append(user_id)
            query = f'UPDATE api_settings SET {", ".join(updates)}, updated_at = %s WHERE user_id = %s'
            cursor.execute(query, values)
    
    # ============================================
    # NOTIFICATION METHODS
    # ============================================
    
    def get_notification_settings(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM notifications WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            if not result:
                cursor.execute('INSERT INTO notifications (user_id, email_enabled) VALUES (%s, 1) ON CONFLICT (user_id) DO NOTHING', (user_id,))
                cursor.execute('SELECT * FROM notifications WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_notification_settings(self, user_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = %s")
                values.append(1 if value else 0)
            values.append(user_id)
            query = f'UPDATE notifications SET {", ".join(updates)} WHERE user_id = %s'
            cursor.execute(query, values)
    
    # ============================================
    # CAMPAIGN METHODS
    # ============================================
    
    def create_campaign(self, user_id, name, industry, script, default_location=""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now()
            cursor.execute('''
                INSERT INTO campaigns (user_id, name, industry, script, default_location, created_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            ''', (user_id, name, industry, script, default_location, created_at))
            campaign_id = cursor.fetchone()['id']
            return campaign_id
    
    def get_user_campaigns(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM campaigns WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    def get_campaign(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM campaigns WHERE id = %s', (campaign_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def delete_campaign(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM business_searches WHERE campaign_id = %s', (campaign_id,))
            cursor.execute('DELETE FROM messages WHERE lead_id IN (SELECT id FROM leads WHERE campaign_id = %s)', (campaign_id,))
            cursor.execute('DELETE FROM leads WHERE campaign_id = %s', (campaign_id,))
            cursor.execute('DELETE FROM campaigns WHERE id = %s', (campaign_id,))
    
    # ============================================
    # LEAD METHODS
    # ============================================
    
    def add_leads(self, campaign_id, leads_data):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now()
            added = 0
            
            for lead in leads_data:
                cursor.execute('''
                    INSERT INTO leads (campaign_id, name, email, company, website, phone, address, rating, total_ratings, place_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (campaign_id, lead.get('name'), lead.get('email', ''), 
                      lead.get('company'), lead.get('website', ''), lead.get('phone', ''),
                      lead.get('address', ''), lead.get('rating', 0), lead.get('total_ratings', 0),
                      lead.get('place_id', ''), created_at))
                added += 1
            
            return added
    
    def get_campaign_leads(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads WHERE campaign_id = %s ORDER BY score DESC, created_at ASC', (campaign_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    def get_lead(self, lead_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads WHERE id = %s', (lead_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_lead(self, lead_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = %s")
                values.append(value)
            values.append(lead_id)
            query = f'UPDATE leads SET {", ".join(updates)} WHERE id = %s'
            cursor.execute(query, values)
    
    def update_lead_score(self, lead_id, score, score_reason=None, personalized_message=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if personalized_message and score_reason:
                cursor.execute('''
                    UPDATE leads SET score = %s, score_reason = %s, personalized_message = %s, status = %s
                    WHERE id = %s
                ''', (score, score_reason, personalized_message, 'scored', lead_id))
            elif personalized_message:
                cursor.execute('''
                    UPDATE leads SET score = %s, personalized_message = %s, status = %s
                    WHERE id = %s
                ''', (score, personalized_message, 'scored', lead_id))
            elif score_reason:
                cursor.execute('''
                    UPDATE leads SET score = %s, score_reason = %s, status = %s
                    WHERE id = %s
                ''', (score, score_reason, 'scored', lead_id))
            else:
                cursor.execute('''
                    UPDATE leads SET score = %s, status = %s
                    WHERE id = %s
                ''', (score, 'scored', lead_id))
    
    def update_website_analysis(self, lead_id, analysis, issues, recommendations):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE leads SET 
                    website_analyzed = 1, 
                    website_analysis = %s, 
                    website_issues = %s, 
                    website_recommendations = %s
                WHERE id = %s
            ''', (analysis, issues, recommendations, lead_id))
    
    def mark_email_sent(self, lead_id, message_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('UPDATE leads SET email_sent = 1, email_sent_at = %s, status = %s WHERE id = %s', (now, 'contacted', lead_id))
            cursor.execute('UPDATE messages SET status = %s, sent_at = %s WHERE id = %s', ('sent', now, message_id))
    
    def mark_meeting_scheduled(self, lead_id, meeting_link, meeting_time):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE leads SET meeting_scheduled = 1, meeting_link = %s, meeting_time = %s, status = %s
                WHERE id = %s
            ''', (meeting_link, meeting_time, 'meeting_scheduled', lead_id))
    
    def mark_replied(self, lead_id, message_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('UPDATE leads SET replied = 1, status = %s WHERE id = %s', ('replied', lead_id))
            cursor.execute('UPDATE messages SET replied_at = %s WHERE id = %s', (now, message_id))
    
    # ============================================
    # MESSAGE METHODS
    # ============================================
    
    def save_message(self, lead_id, subject, content, status='pending'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (lead_id, subject, content, status)
                VALUES (%s, %s, %s, %s) RETURNING id
            ''', (lead_id, subject, content, status))
            return cursor.fetchone()['id']
    
    def get_lead_messages(self, lead_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE lead_id = %s ORDER BY sent_at DESC', (lead_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # BUSINESS SEARCH METHODS
    # ============================================
    
    def save_business_search(self, user_id, campaign_id, keyword, location, total_results, source='openstreetmap'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO business_searches (user_id, campaign_id, keyword, location, total_results, source, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (user_id, campaign_id, keyword, location, total_results, source, datetime.now()))
            return cursor.lastrowid
    
    def get_business_searches(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM business_searches WHERE campaign_id = %s ORDER BY created_at DESC', (campaign_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # STATS METHODS
    # ============================================
    
    def get_campaign_stats(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s', (campaign_id,))
            total_leads = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND score >= 7', (campaign_id,))
            hot_leads = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND email_sent = 1', (campaign_id,))
            messages_sent = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND replied = 1', (campaign_id,))
            replies = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND opened = 1', (campaign_id,))
            opens = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND meeting_scheduled = 1', (campaign_id,))
            meetings = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = %s AND website_analyzed = 1', (campaign_id,))
            websites_analyzed = cursor.fetchone()['count']
            
            return {
                'total_leads': total_leads,
                'hot_leads': hot_leads,
                'messages_sent': messages_sent,
                'replies': replies,
                'opens': opens,
                'meetings': meetings,
                'websites_analyzed': websites_analyzed
            }
    
    def get_all_leads_for_processing(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT l.*, c.industry, c.script 
                FROM leads l 
                JOIN campaigns c ON l.campaign_id = c.id 
                WHERE c.user_id = %s AND l.score = 0
                LIMIT 50
            ''', (user_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # INTERSEND PAYMENT METHODS
    # ============================================
    
    def save_intersend_payment(self, user_id, order_id, provider_payment_id, amount, 
                                currency, status='pending', checkout_url=None, 
                                payment_method='card'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                INSERT INTO intersend_payments 
                (user_id, order_id, provider_payment_id, amount, currency, 
                 status, checkout_url, payment_method, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                RETURNING id
            ''', (user_id, order_id, provider_payment_id, amount, currency,
                  status, checkout_url, payment_method, now, now))
            return cursor.fetchone()['id']
    
    def get_intersend_payment_by_order_id(self, order_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM intersend_payments WHERE order_id = %s', (order_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def get_intersend_payment_by_provider_id(self, provider_payment_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM intersend_payments WHERE provider_payment_id = %s', (provider_payment_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def complete_intersend_payment(self, provider_payment_id, transaction_id=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                UPDATE intersend_payments 
                SET status = 'completed', 
                    completed_at = %s, 
                    updated_at = %s,
                    transaction_id = %s
                WHERE provider_payment_id = %s AND status = 'pending'
                RETURNING *
            ''', (now, now, transaction_id, provider_payment_id))
            result = cursor.fetchone()
            
            if result:
                # Also grant access via user_access
                self.grant_lifetime_access(result['user_id'], result['id'])
            
            return self._row_to_dict(result)
    
    def update_intersend_payment_status(self, provider_payment_id, status):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                UPDATE intersend_payments 
                SET status = %s, updated_at = %s
                WHERE provider_payment_id = %s
            ''', (status, now, provider_payment_id))
    
    def get_user_intersend_payments(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM intersend_payments 
                WHERE user_id = %s 
                ORDER BY created_at DESC
            ''', (user_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # USER ACCESS METHODS (Updated with Trial)
    # ============================================
    
    def user_has_lifetime_access(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT has_lifetime_access FROM user_access WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            if result:
                return result['has_lifetime_access'] == 1
            return False
    
    def user_has_access(self, user_id):
        """
        Check if user has access (lifetime OR active trial)
        """
        # Check lifetime access first
        if self.user_has_lifetime_access(user_id):
            return True
        
        # Check trial
        return self.is_trial_active(user_id)
    
    def get_access_status(self, user_id):
        """
        Get detailed access status for a user
        Returns: dict with access type and expiry info
        """
        # Check lifetime access
        if self.user_has_lifetime_access(user_id):
            return {
                'has_access': True,
                'access_type': 'lifetime',
                'message': 'Lifetime access - unlimited'
            }
        
        # Check trial
        trial_status = self.get_user_trial_status(user_id)
        if trial_status and trial_status.get('trial_ended_at'):
            now = datetime.now()
            trial_end = trial_status['trial_ended_at']
            if now < trial_end:
                days_left = (trial_end - now).days
                hours_left = (trial_end - now).seconds // 3600
                return {
                    'has_access': True,
                    'access_type': 'trial',
                    'days_left': days_left,
                    'hours_left': hours_left,
                    'expires_at': trial_end,
                    'message': f'Trial access - {days_left} days left' if days_left > 0 else f'Trial access - {hours_left} hours left'
                }
            else:
                return {
                    'has_access': False,
                    'access_type': 'expired',
                    'message': 'Trial expired - Please purchase lifetime access'
                }
        
        return {
            'has_access': False,
            'access_type': 'none',
            'message': 'No access - Please purchase lifetime access or start a trial'
        }
    
    def grant_lifetime_access(self, user_id, payment_id=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now()
            if payment_id:
                cursor.execute('''
                    INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at, payment_id)
                    VALUES (%s, 1, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        has_lifetime_access = 1,
                        access_granted_at = %s,
                        payment_id = %s
                ''', (user_id, now, payment_id, now, payment_id))
            else:
                cursor.execute('''
                    INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at)
                    VALUES (%s, 1, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        has_lifetime_access = 1,
                        access_granted_at = %s
                ''', (user_id, now, now))
    
    def get_user_payment_info(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ua.has_lifetime_access, ua.access_granted_at, 
                       ip.amount, ip.currency, ip.completed_at, 
                       ip.order_id, ip.status, ip.payment_method
                FROM user_access ua
                LEFT JOIN intersend_payments ip ON ua.payment_id = ip.id
                WHERE ua.user_id = %s
                ORDER BY ip.created_at DESC
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
                    'order_id': result['order_id'],
                    'status': result['status'],
                    'payment_method': result['payment_method']
                }
            return {'has_access': False, 'status': None}

# Initialize singleton
db = Database()