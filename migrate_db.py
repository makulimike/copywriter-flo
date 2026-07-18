# migrate_db.py - Add trial columns to database

import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

def run_migration():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found in .env")
        return
    
    try:
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🔧 Adding trial columns to users table...")
        
        # Add trial columns
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS trial_ended_at TIMESTAMP
        """)
        
        # Update existing users to have a trial (3 days)
        cursor.execute("""
            UPDATE users 
            SET trial_started_at = NOW(), 
                trial_ended_at = NOW() + INTERVAL '3 days' 
            WHERE trial_started_at IS NULL
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        print("   - Added trial_started_at column")
        print("   - Added trial_ended_at column")
        print("   - Set trial for existing users (3 days)")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()