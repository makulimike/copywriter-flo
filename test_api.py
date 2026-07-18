import requests
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get('COINGATE_API_KEY')
print(f"API Key: {api_key}")
print(f"API Key length: {len(api_key) if api_key else 0}")

if not api_key:
    print("❌ API key not found in .env")
else:
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    response = requests.get(
        'https://api-sandbox.coingate.com/v2/orders',
        headers=headers,
        timeout=10
    )
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ API key is valid!")
    else:
        print(f"❌ API key error: {response.text}")