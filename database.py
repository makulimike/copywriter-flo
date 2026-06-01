# database.py - Updated version with proper PostgreSQL row handling

import os
import sys
from datetime import datetime
from contextlib import contextmanager

# Try to import PostgreSQL, fallback to SQLite
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    import sqlite3

class Database:
    def __init__(self, db_path="copywriter.db"):
        self.db_path = db_path
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_postgres = self.database_url is not None and POSTGRES_AVAILABLE
        
        if self.use_postgres:
            print("✅ Using PostgreSQL database (persistent)")
        else:
            print("✅ Using SQLite database (local)")
        
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        if self.use_postgres:
            # Use RealDictCursor to get dictionary-like rows
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
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()
    
    def _row_to_dict(self, row):
        """Convert database row to dictionary consistently"""
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
        return dict(row)
    
    def _execute(self, cursor, query, params=None):
        """Helper to execute queries with parameter placeholders"""
        if self.use_postgres:
            # Convert ? to %s for PostgreSQL
            query = query.replace('?', '%s')
        if params:
            return cursor.execute(query, params)
        return cursor.execute(query)
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if self.use_postgres:
                # PostgreSQL syntax
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
                        created_at TEXT NOT NULL
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS api_settings (
                        user_id INTEGER PRIMARY KEY,
                        openai_model TEXT DEFAULT 'gpt-3.5-turbo',
                        smtp_host TEXT DEFAULT 'smtp.gmail.com',
                        smtp_port INTEGER DEFAULT 587,
                        smtp_user TEXT,
                        smtp_password TEXT,
                        auto_send_enabled INTEGER DEFAULT 0,
                        auto_send_score INTEGER DEFAULT 7,
                        meeting_link TEXT,
                        google_meet_enabled INTEGER DEFAULT 0,
                        updated_at TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS campaigns (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        industry TEXT,
                        script TEXT,
                        default_location TEXT,
                        status TEXT DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        campaign_id INTEGER NOT NULL,
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
                        email_sent_at TEXT,
                        opened INTEGER DEFAULT 0,
                        replied INTEGER DEFAULT 0,
                        meeting_scheduled INTEGER DEFAULT 0,
                        meeting_link TEXT,
                        meeting_time TEXT,
                        confirmation_token TEXT,
                        confirmation_sent_at TEXT,
                        website_analyzed INTEGER DEFAULT 0,
                        website_analysis TEXT,
                        website_issues TEXT,
                        website_recommendations TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        lead_id INTEGER NOT NULL,
                        subject TEXT,
                        content TEXT,
                        sent_at TEXT,
                        status TEXT DEFAULT 'pending',
                        opened_at TEXT,
                        replied_at TEXT,
                        error_message TEXT,
                        FOREIGN KEY (lead_id) REFERENCES leads (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS notifications (
                        user_id INTEGER PRIMARY KEY,
                        email_enabled INTEGER DEFAULT 1,
                        sms_enabled INTEGER DEFAULT 0,
                        whatsapp_enabled INTEGER DEFAULT 0,
                        telegram_enabled INTEGER DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS business_searches (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        campaign_id INTEGER NOT NULL,
                        keyword TEXT NOT NULL,
                        location TEXT,
                        total_results INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'openstreetmap',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS payments (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        stripe_session_id TEXT UNIQUE NOT NULL,
                        amount INTEGER,
                        currency TEXT,
                        status TEXT DEFAULT 'completed',
                        payment_date TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_access (
                        user_id INTEGER PRIMARY KEY,
                        has_lifetime_access INTEGER DEFAULT 0,
                        access_granted_at TEXT,
                        payment_id INTEGER,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        FOREIGN KEY (payment_id) REFERENCES payments (id)
                    )
                ''')
                
            else:
                # SQLite syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        email TEXT NOT NULL,
                        phone TEXT,
                        whatsapp_number TEXT,
                        telegram_chat_id TEXT,
                        meeting_link TEXT,
                        created_at TEXT NOT NULL
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS api_settings (
                        user_id INTEGER PRIMARY KEY,
                        openai_model TEXT DEFAULT 'gpt-3.5-turbo',
                        smtp_host TEXT DEFAULT 'smtp.gmail.com',
                        smtp_port INTEGER DEFAULT 587,
                        smtp_user TEXT,
                        smtp_password TEXT,
                        auto_send_enabled INTEGER DEFAULT 0,
                        auto_send_score INTEGER DEFAULT 7,
                        meeting_link TEXT,
                        google_meet_enabled INTEGER DEFAULT 0,
                        updated_at TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS campaigns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        industry TEXT,
                        script TEXT,
                        default_location TEXT,
                        status TEXT DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        campaign_id INTEGER NOT NULL,
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
                        email_sent_at TEXT,
                        opened INTEGER DEFAULT 0,
                        replied INTEGER DEFAULT 0,
                        meeting_scheduled INTEGER DEFAULT 0,
                        meeting_link TEXT,
                        meeting_time TEXT,
                        confirmation_token TEXT,
                        confirmation_sent_at TEXT,
                        website_analyzed INTEGER DEFAULT 0,
                        website_analysis TEXT,
                        website_issues TEXT,
                        website_recommendations TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lead_id INTEGER NOT NULL,
                        subject TEXT,
                        content TEXT,
                        sent_at TEXT,
                        status TEXT DEFAULT 'pending',
                        opened_at TEXT,
                        replied_at TEXT,
                        error_message TEXT,
                        FOREIGN KEY (lead_id) REFERENCES leads (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS notifications (
                        user_id INTEGER PRIMARY KEY,
                        email_enabled INTEGER DEFAULT 1,
                        sms_enabled INTEGER DEFAULT 0,
                        whatsapp_enabled INTEGER DEFAULT 0,
                        telegram_enabled INTEGER DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS business_searches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        campaign_id INTEGER NOT NULL,
                        keyword TEXT NOT NULL,
                        location TEXT,
                        total_results INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'openstreetmap',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        stripe_session_id TEXT UNIQUE NOT NULL,
                        amount INTEGER,
                        currency TEXT,
                        status TEXT DEFAULT 'completed',
                        payment_date TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_access (
                        user_id INTEGER PRIMARY KEY,
                        has_lifetime_access INTEGER DEFAULT 0,
                        access_granted_at TEXT,
                        payment_id INTEGER,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        FOREIGN KEY (payment_id) REFERENCES payments (id)
                    )
                ''')
    
    # ============================================
    # USER METHODS
    # ============================================
    
    def create_user(self, username, password, email, phone="", whatsapp_number=""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now().isoformat()
            
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO users (username, password, email, phone, whatsapp_number, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', (username, password, email, phone, whatsapp_number, created_at))
                user_id = cursor.fetchone()['id']
            else:
                cursor.execute('''
                    INSERT INTO users (username, password, email, phone, whatsapp_number, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (username, password, email, phone, whatsapp_number, created_at))
                user_id = cursor.lastrowid
            
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO notifications (user_id, email_enabled)
                    VALUES (%s, 1) ON CONFLICT (user_id) DO NOTHING
                ''', (user_id,))
                cursor.execute('''
                    INSERT INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                    VALUES (%s, 0, 7, 0, %s) ON CONFLICT (user_id) DO NOTHING
                ''', (user_id, datetime.now().isoformat()))
            else:
                cursor.execute('''
                    INSERT OR IGNORE INTO notifications (user_id, email_enabled)
                    VALUES (?, 1)
                ''', (user_id,))
                cursor.execute('''
                    INSERT OR IGNORE INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                    VALUES (?, 0, 7, 0, ?)
                ''', (user_id, datetime.now().isoformat()))
            
            return user_id
    
    def get_user_by_username(self, username):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
            else:
                cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
            else:
                cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    # ============================================
    # API SETTINGS METHODS
    # ============================================
    
    def get_api_settings(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM api_settings WHERE user_id = %s', (user_id,))
            else:
                cursor.execute('SELECT * FROM api_settings WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                if self.use_postgres:
                    cursor.execute('''
                        INSERT INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                        VALUES (%s, 0, 7, 0, %s) ON CONFLICT (user_id) DO NOTHING
                    ''', (user_id, datetime.now().isoformat()))
                    cursor.execute('SELECT * FROM api_settings WHERE user_id = %s', (user_id,))
                else:
                    cursor.execute('''
                        INSERT OR IGNORE INTO api_settings (user_id, auto_send_enabled, auto_send_score, google_meet_enabled, updated_at)
                        VALUES (?, 0, 7, 0, ?)
                    ''', (user_id, datetime.now().isoformat()))
                    cursor.execute('SELECT * FROM api_settings WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_api_settings(self, user_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)
            values.append(datetime.now().isoformat())
            values.append(user_id)
            query = f'UPDATE api_settings SET {", ".join(updates)}, updated_at = ? WHERE user_id = ?'
            self._execute(cursor, query, values)
    
    # ============================================
    # NOTIFICATION METHODS
    # ============================================
    
    def get_notification_settings(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM notifications WHERE user_id = %s', (user_id,))
            else:
                cursor.execute('SELECT * FROM notifications WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                if self.use_postgres:
                    cursor.execute('INSERT INTO notifications (user_id, email_enabled) VALUES (%s, 1) ON CONFLICT (user_id) DO NOTHING', (user_id,))
                    cursor.execute('SELECT * FROM notifications WHERE user_id = %s', (user_id,))
                else:
                    cursor.execute('INSERT OR IGNORE INTO notifications (user_id, email_enabled) VALUES (?, 1)', (user_id,))
                    cursor.execute('SELECT * FROM notifications WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_notification_settings(self, user_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(1 if value else 0)
            values.append(user_id)
            query = f'UPDATE notifications SET {", ".join(updates)} WHERE user_id = ?'
            self._execute(cursor, query, values)
    
    # ============================================
    # CAMPAIGN METHODS
    # ============================================
    
    def create_campaign(self, user_id, name, industry, script, default_location=""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now().isoformat()
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO campaigns (user_id, name, industry, script, default_location, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', (user_id, name, industry, script, default_location, created_at))
                campaign_id = cursor.fetchone()['id']
            else:
                cursor.execute('''
                    INSERT INTO campaigns (user_id, name, industry, script, default_location, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, name, industry, script, default_location, created_at))
                campaign_id = cursor.lastrowid
            return campaign_id
    
    def get_user_campaigns(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM campaigns WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
            else:
                cursor.execute('SELECT * FROM campaigns WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    def get_campaign(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM campaigns WHERE id = %s', (campaign_id,))
            else:
                cursor.execute('SELECT * FROM campaigns WHERE id = ?', (campaign_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def delete_campaign(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('DELETE FROM business_searches WHERE campaign_id = %s', (campaign_id,))
                cursor.execute('DELETE FROM messages WHERE lead_id IN (SELECT id FROM leads WHERE campaign_id = %s)', (campaign_id,))
                cursor.execute('DELETE FROM leads WHERE campaign_id = %s', (campaign_id,))
                cursor.execute('DELETE FROM campaigns WHERE id = %s', (campaign_id,))
            else:
                cursor.execute('DELETE FROM business_searches WHERE campaign_id = ?', (campaign_id,))
                cursor.execute('DELETE FROM messages WHERE lead_id IN (SELECT id FROM leads WHERE campaign_id = ?)', (campaign_id,))
                cursor.execute('DELETE FROM leads WHERE campaign_id = ?', (campaign_id,))
                cursor.execute('DELETE FROM campaigns WHERE id = ?', (campaign_id,))
    
    # ============================================
    # LEAD METHODS
    # ============================================
    
    def add_leads(self, campaign_id, leads_data):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now().isoformat()
            added = 0
            
            for lead in leads_data:
                if self.use_postgres:
                    cursor.execute('''
                        INSERT INTO leads (campaign_id, name, email, company, website, phone, address, rating, total_ratings, place_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (campaign_id, lead.get('name'), lead.get('email', ''), 
                          lead.get('company'), lead.get('website', ''), lead.get('phone', ''),
                          lead.get('address', ''), lead.get('rating', 0), lead.get('total_ratings', 0),
                          lead.get('place_id', ''), created_at))
                else:
                    cursor.execute('''
                        INSERT INTO leads (campaign_id, name, email, company, website, phone, address, rating, total_ratings, place_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (campaign_id, lead.get('name'), lead.get('email', ''), 
                          lead.get('company'), lead.get('website', ''), lead.get('phone', ''),
                          lead.get('address', ''), lead.get('rating', 0), lead.get('total_ratings', 0),
                          lead.get('place_id', ''), created_at))
                added += 1
            
            return added
    
    def get_campaign_leads(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM leads WHERE campaign_id = %s ORDER BY score DESC, created_at ASC', (campaign_id,))
            else:
                cursor.execute('SELECT * FROM leads WHERE campaign_id = ? ORDER BY score DESC, created_at ASC', (campaign_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    def get_lead(self, lead_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM leads WHERE id = %s', (lead_id,))
            else:
                cursor.execute('SELECT * FROM leads WHERE id = ?', (lead_id,))
            result = cursor.fetchone()
            return self._row_to_dict(result)
    
    def update_lead(self, lead_id, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)
            values.append(lead_id)
            query = f'UPDATE leads SET {", ".join(updates)} WHERE id = ?'
            self._execute(cursor, query, values)
    
    def update_lead_score(self, lead_id, score, score_reason=None, personalized_message=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if personalized_message and score_reason:
                query = '''
                    UPDATE leads SET score = ?, score_reason = ?, personalized_message = ?, status = ?
                    WHERE id = ?
                '''
                self._execute(cursor, query, (score, score_reason, personalized_message, 'scored', lead_id))
            elif personalized_message:
                query = 'UPDATE leads SET score = ?, personalized_message = ?, status = ? WHERE id = ?'
                self._execute(cursor, query, (score, personalized_message, 'scored', lead_id))
            elif score_reason:
                query = 'UPDATE leads SET score = ?, score_reason = ?, status = ? WHERE id = ?'
                self._execute(cursor, query, (score, score_reason, 'scored', lead_id))
            else:
                query = 'UPDATE leads SET score = ?, status = ? WHERE id = ?'
                self._execute(cursor, query, (score, 'scored', lead_id))
    
    def update_website_analysis(self, lead_id, analysis, issues, recommendations):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                UPDATE leads SET 
                    website_analyzed = 1, 
                    website_analysis = ?, 
                    website_issues = ?, 
                    website_recommendations = ?
                WHERE id = ?
            '''
            self._execute(cursor, query, (analysis, issues, recommendations, lead_id))
    
    def mark_email_sent(self, lead_id, message_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            query1 = 'UPDATE leads SET email_sent = 1, email_sent_at = ?, status = ? WHERE id = ?'
            query2 = 'UPDATE messages SET status = ?, sent_at = ? WHERE id = ?'
            self._execute(cursor, query1, (now, 'contacted', lead_id))
            self._execute(cursor, query2, ('sent', now, message_id))
    
    def mark_meeting_scheduled(self, lead_id, meeting_link, meeting_time):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                UPDATE leads SET meeting_scheduled = 1, meeting_link = ?, meeting_time = ?, status = ?
                WHERE id = ?
            '''
            self._execute(cursor, query, (meeting_link, meeting_time, 'meeting_scheduled', lead_id))
    
    def mark_replied(self, lead_id, message_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            query1 = 'UPDATE leads SET replied = 1, status = "replied" WHERE id = ?'
            query2 = 'UPDATE messages SET replied_at = ? WHERE id = ?'
            self._execute(cursor, query1, (lead_id,))
            self._execute(cursor, query2, (now, message_id))
    
    # ============================================
    # MESSAGE METHODS
    # ============================================
    
    def save_message(self, lead_id, subject, content, status='pending'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO messages (lead_id, subject, content, status)
                    VALUES (%s, %s, %s, %s) RETURNING id
                ''', (lead_id, subject, content, status))
                return cursor.fetchone()['id']
            else:
                cursor.execute('''
                    INSERT INTO messages (lead_id, subject, content, status)
                    VALUES (?, ?, ?, ?)
                ''', (lead_id, subject, content, status))
                return cursor.lastrowid
    
    def get_lead_messages(self, lead_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM messages WHERE lead_id = %s ORDER BY sent_at DESC', (lead_id,))
            else:
                cursor.execute('SELECT * FROM messages WHERE lead_id = ? ORDER BY sent_at DESC', (lead_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # BUSINESS SEARCH METHODS
    # ============================================
    
    def save_business_search(self, user_id, campaign_id, keyword, location, total_results, source='openstreetmap'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO business_searches (user_id, campaign_id, keyword, location, total_results, source, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (user_id, campaign_id, keyword, location, total_results, source, datetime.now().isoformat()))
                return cursor.lastrowid
            else:
                cursor.execute('''
                    INSERT INTO business_searches (user_id, campaign_id, keyword, location, total_results, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, campaign_id, keyword, location, total_results, source, datetime.now().isoformat()))
                return cursor.lastrowid
    
    def get_business_searches(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT * FROM business_searches WHERE campaign_id = %s ORDER BY created_at DESC', (campaign_id,))
            else:
                cursor.execute('SELECT * FROM business_searches WHERE campaign_id = ? ORDER BY created_at DESC', (campaign_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # STATS METHODS
    # ============================================
    
    def get_campaign_stats(self, campaign_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if self.use_postgres:
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
            else:
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ?', (campaign_id,))
                total_leads = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND score >= 7', (campaign_id,))
                hot_leads = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND email_sent = 1', (campaign_id,))
                messages_sent = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND replied = 1', (campaign_id,))
                replies = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND opened = 1', (campaign_id,))
                opens = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND meeting_scheduled = 1', (campaign_id,))
                meetings = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND website_analyzed = 1', (campaign_id,))
                websites_analyzed = cursor.fetchone()[0]
            
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
            if self.use_postgres:
                cursor.execute('''
                    SELECT l.*, c.industry, c.script 
                    FROM leads l 
                    JOIN campaigns c ON l.campaign_id = c.id 
                    WHERE c.user_id = %s AND l.score = 0
                    LIMIT 50
                ''', (user_id,))
            else:
                cursor.execute('''
                    SELECT l.*, c.industry, c.script 
                    FROM leads l 
                    JOIN campaigns c ON l.campaign_id = c.id 
                    WHERE c.user_id = ? AND l.score = 0
                    LIMIT 50
                ''', (user_id,))
            results = cursor.fetchall()
            return [self._row_to_dict(r) for r in results] if results else []
    
    # ============================================
    # PAYMENT & ACCESS METHODS
    # ============================================
    
    def user_has_lifetime_access(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('SELECT has_lifetime_access FROM user_access WHERE user_id = %s', (user_id,))
            else:
                cursor.execute('SELECT has_lifetime_access FROM user_access WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                if self.use_postgres:
                    return result['has_lifetime_access'] == 1
                else:
                    return result[0] == 1
            return False
    
    def grant_lifetime_access(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at)
                    VALUES (%s, 1, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        has_lifetime_access = 1,
                        access_granted_at = %s
                ''', (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
            else:
                cursor.execute('''
                    INSERT INTO user_access (user_id, has_lifetime_access, access_granted_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        has_lifetime_access = 1,
                        access_granted_at = ?
                ''', (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
    
    def get_user_payment_info(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('''
                    SELECT ua.has_lifetime_access, ua.access_granted_at, 
                           p.amount, p.currency, p.payment_date, p.stripe_session_id
                    FROM user_access ua
                    LEFT JOIN payments p ON ua.payment_id = p.id
                    WHERE ua.user_id = %s
                ''', (user_id,))
            else:
                cursor.execute('''
                    SELECT ua.has_lifetime_access, ua.access_granted_at, 
                           p.amount, p.currency, p.payment_date, p.stripe_session_id
                    FROM user_access ua
                    LEFT JOIN payments p ON ua.payment_id = p.id
                    WHERE ua.user_id = ?
                ''', (user_id,))
            result = cursor.fetchone()
            if result:
                if self.use_postgres:
                    return {
                        'has_access': result['has_lifetime_access'] == 1,
                        'granted_at': result['access_granted_at'],
                        'amount': result['amount'],
                        'currency': result['currency'],
                        'payment_date': result['payment_date'],
                        'session_id': result['stripe_session_id']
                    }
                else:
                    return {
                        'has_access': result[0] == 1,
                        'granted_at': result[1],
                        'amount': result[2],
                        'currency': result[3],
                        'payment_date': result[4],
                        'session_id': result[5]
                    }
            return {'has_access': False}
    
    def save_payment_record(self, user_id, session_id, payment_intent, amount, currency):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.use_postgres:
                cursor.execute('''
                    INSERT INTO payments (user_id, stripe_session_id, stripe_payment_intent, amount, currency, payment_date)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', (user_id, session_id, payment_intent, amount, currency, datetime.now().isoformat()))
                payment_id = cursor.fetchone()['id']
                cursor.execute('UPDATE user_access SET payment_id = %s WHERE user_id = %s', (payment_id, user_id))
            else:
                cursor.execute('''
                    INSERT INTO payments (user_id, stripe_session_id, stripe_payment_intent, amount, currency, payment_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, session_id, payment_intent, amount, currency, datetime.now().isoformat()))
                payment_id = cursor.lastrowid
                cursor.execute('UPDATE user_access SET payment_id = ? WHERE user_id = ?', (payment_id, user_id))
            return payment_id