# test_osm.py
import requests

print("=" * 60)
print("Testing OpenStreetMap Search")
print("=" * 60)

# Test different searches
test_searches = [
    ("restaurant", "Nairobi"),
    ("hotel", "Nairobi"),
    ("coffee", "Nairobi"),
    ("salon", "Nairobi"),
    ("clinic", "Nairobi"),
]

for keyword, location in test_searches:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': f"{keyword} in {location}",
        'format': 'json',
        'limit': 5
    }
    headers = {'User-Agent': 'Copywriterflo/1.0 (test)'}
    
    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        print(f"\n🔍 '{keyword}' in {location}: Found {len(data)} results")
        for place in data[:3]:
            name = place.get('display_name', '').split(',')[0]
            print(f"   - {name}")
    except Exception as e:
        print(f"Error: {e}")

print("\n" + "=" * 60)
print("If you see 0 results, try:")
print("  - Make sure you have internet connection")
print("  - The API might be rate limiting (wait a minute)")
print("  - Try a different location like 'Mombasa' or 'Kisumu'")
print("=" * 60)