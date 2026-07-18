import os
from dotenv import load_dotenv
load_dotenv()

from database import Database
db = Database()

print('✅ Using PostgreSQL:', db.use_postgres)
print('✅ Database URL:', db.database_url[:50] + '...' if db.database_url else 'Not set')

# Test connection
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT version()')
    version = cursor.fetchone()
    # Access by key name for RealDictCursor
    version_text = version['version'] if isinstance(version, dict) else version[0]
    print('✅ PostgreSQL Version:', version_text[:30] + '...')
    print('✅ Connection successful!')
    
    # Test creating a simple table to verify permissions
    cursor.execute("SELECT current_database()")
    db_name = cursor.fetchone()
    db_name_text = db_name['current_database'] if isinstance(db_name, dict) else db_name[0]
    print('✅ Connected to database:', db_name_text)
    print('✅ All systems ready!')
