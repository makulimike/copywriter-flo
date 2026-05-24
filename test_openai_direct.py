# test_openai_direct.py
import openai
import sqlite3
import os

def test_openai_api():
    print("=" * 60)
    print("🧪 TESTING OPENAI API DIRECTLY")
    print("=" * 60)
    
    # Get API key from database for user mike20 (ID: 2)
    conn = sqlite3.connect('copywriter.db')
    cursor = conn.cursor()
    cursor.execute("SELECT openai_api_key FROM api_settings WHERE user_id = 2")
    result = cursor.fetchone()
    
    if not result or not result[0]:
        print("❌ No API key found for user 2 in database")
        return
    
    api_key = result[0]
    print(f"\n✅ Found API key: {api_key[:20]}...")
    print(f"✅ API key length: {len(api_key)}")
    print(f"✅ Starts with sk-: {api_key.startswith('sk-')}")
    
    # Test the API directly
    print("\n" + "=" * 60)
    print("📡 TESTING OPENAI API CALL")
    print("=" * 60)
    
    try:
        # Initialize client
        print("\n1. Creating OpenAI client...")
        client = openai.OpenAI(api_key=api_key)
        print("   ✅ Client created successfully")
        
        # Make a simple test call
        print("\n2. Making test API call...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "Say 'API is working!' in 5 words or less"}
            ],
            max_tokens=20
        )
        
        result = response.choices[0].message.content
        print(f"   ✅ API call successful!")
        print(f"   📝 Response: {result}")
        
        print("\n" + "=" * 60)
        print("✅ OPENAI API IS WORKING CORRECTLY!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print(f"\nError type: {type(e).__name__}")
        
        if "authentication" in str(e).lower():
            print("\n💡 This is an authentication error. Possible causes:")
            print("   1. API key is invalid")
            print("   2. API key has expired")
            print("   3. API key doesn't have access to GPT-3.5")
            print("\n   Go to https://platform.openai.com/api-keys to check your key")
        elif "rate limit" in str(e).lower():
            print("\n💡 Rate limit exceeded. Try again in a few seconds.")
        elif "ChatCompletion" in str(e):
            print("\n💡 This is a library version issue. Run:")
            print("   pip install --upgrade openai")
        else:
            print("\n💡 Unknown error. Check your internet connection and API key.")
    
    conn.close()

if __name__ == '__main__':
    test_openai_api()