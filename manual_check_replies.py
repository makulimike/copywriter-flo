# manual_check_replies.py
import sqlite3
import imaplib
import email
from email.utils import parseaddr

def manual_check():
    print("=" * 60)
    print("🔍 MANUAL REPLY CHECK")
    print("=" * 60)
    
    conn = sqlite3.connect('copywriter.db')
    cursor = conn.cursor()
    
    # Get user with SMTP configured
    cursor.execute("SELECT user_id, smtp_user, smtp_password FROM api_settings WHERE smtp_user IS NOT NULL")
    settings = cursor.fetchall()
    
    if not settings:
        print("❌ No SMTP settings found in database")
        return
    
    for setting in settings:
        user_id = setting[0]
        smtp_user = setting[1]
        smtp_password = setting[2]
        
        print(f"\n📧 Checking emails for user: {smtp_user}")
        
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(smtp_user, smtp_password)
            mail.select("INBOX")
            
            # Search for unread emails
            result, data = mail.search(None, 'UNSEEN')
            
            if result == 'OK' and data[0]:
                email_ids = data[0].split()
                print(f"✅ Found {len(email_ids)} unread emails")
                
                for num in email_ids[:5]:  # Check first 5
                    result, msg_data = mail.fetch(num, "(RFC822)")
                    if result == 'OK':
                        msg = email.message_from_bytes(msg_data[0][1])
                        from_email = parseaddr(msg['From'])[1]
                        subject = msg['Subject']
                        print(f"\n📨 Email from: {from_email}")
                        print(f"   Subject: {subject}")
                        
                        # Check if this email is from a lead
                        cursor.execute("""
                            SELECT l.id, l.name, l.email 
                            FROM leads l 
                            JOIN campaigns c ON l.campaign_id = c.id 
                            WHERE l.email = ? AND c.user_id = ?
                        """, (from_email, user_id))
                        lead = cursor.fetchone()
                        
                        if lead:
                            print(f"   ✅ MATCHED to lead: {lead[1]} (ID: {lead[0]})")
                        else:
                            print(f"   ❌ No matching lead found")
            else:
                print("📭 No unread emails found")
            
            mail.close()
            mail.logout()
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    conn.close()

if __name__ == '__main__':
    manual_check()