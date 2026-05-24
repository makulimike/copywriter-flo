from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_wtf.csrf import CSRFProtect
import openai
import hashlib
import secrets
import csv
import io
import time
import threading
import re
import os
import smtplib
import imaplib
import email
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
import json
import uuid
import httpx
from collections import deque
import base64
import html as html_module

load_dotenv()

app = Flask(__name__)

# CSRF Protection
csrf = CSRFProtect()
csrf.init_app(app)

# Get secret keys from environment variables
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise ValueError("SECRET_KEY environment variable is not set. Please add it to .env file")

# Session configuration
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_NAME'] = 'copywriter_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_SECRET_KEY'] = os.environ.get('WTF_CSRF_SECRET_KEY', secrets.token_hex(32))

from database import Database
db = Database()

# ============================================
# STRIPE PAYMENT INTEGRATION
# ============================================

import stripe
from payment import create_payment_session, handle_successful_payment, user_has_lifetime_access, get_payment_status

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
CAMPAIGN_PRICE = int(os.environ.get('CAMPAIGN_PRICE_AMOUNT', 28000))
CURRENCY = os.environ.get('CURRENCY', 'usd')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5000')

# ============================================
# MAKE FUNCTIONS AVAILABLE TO ALL TEMPLATES
# ============================================

@app.context_processor
def utility_processor():
    def check_lifetime_access(user_id):
        if user_id:
            return user_has_lifetime_access(user_id)
        return False
    return dict(user_has_lifetime_access=check_lifetime_access)

# Create a decorator to check payment before accessing paid features
def require_payment(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        
        if not user_has_lifetime_access(session['user_id']):
            flash('You need to purchase lifetime access ($280 one-time) to create campaigns. Pay once, use forever!', 'warning')
            return redirect(url_for('pricing'))
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# GLOBAL OPENAI CLIENT — per-user cache
# ============================================

_openai_clients: dict = {}
_openai_http_client = httpx.Client(
    follow_redirects=True,
    timeout=httpx.Timeout(60.0, connect=10.0),
    trust_env=False,
)

def get_openai_key_from_db(user_id):
    settings = db.get_api_settings(user_id)
    if settings:
        settings_dict = _row_to_dict(settings)
        return settings_dict.get('openai_api_key')
    return None

def init_global_openai_client(user_id):
    if user_id in _openai_clients:
        return _openai_clients[user_id]

    api_key = get_openai_key_from_db(user_id)
    if not api_key:
        print(f"No API key found for user {user_id}")
        return None

    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            timeout=60.0,
            max_retries=2,
            http_client=_openai_http_client,
        )
        _openai_clients[user_id] = client
        print(f"✅ OpenAI client initialised for user {user_id}")
        return client
    except Exception as e:
        print(f"❌ Error creating OpenAI client for user {user_id}: {e}")
        return None

def get_openai_client(user_id):
    return _openai_clients.get(user_id) or init_global_openai_client(user_id)

# ============================================
# HELPER: uniform sqlite3.Row → dict conversion
# ============================================

def _row_to_dict(row):
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)

# ============================================
# RATE LIMITING
# ============================================

class RateLimiter:
    def __init__(self, max_calls=10, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self._lock = threading.Lock()

    def is_allowed(self):
        now = time.time()
        with self._lock:
            while self.calls and self.calls[0] < now - self.period:
                self.calls.popleft()
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return True
        return False

email_rate_limiter = RateLimiter(max_calls=20, period=60)
api_rate_limiter = RateLimiter(max_calls=30, period=60)
nominatim_rate_limiter = RateLimiter(max_calls=1, period=1)

def rate_limit(limiter):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not limiter.is_allowed():
                return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============================================
# BACKGROUND JOB QUEUE WITH APP CONTEXT
# ============================================

class BackgroundJobQueue:
    def __init__(self, app_instance):
        self.queue = deque()
        self.processing = False
        self.lock = threading.Lock()
        self.app = app_instance

    def add_job(self, job_func, *args, **kwargs):
        with self.lock:
            self.queue.append((job_func, args, kwargs))
            if self.processing:
                return
            self.processing = True

        thread = threading.Thread(target=self._worker, daemon=True)
        thread.start()

    def _worker(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.processing = False
                    return
                job = self.queue.popleft()
            try:
                job_func, args, kwargs = job
                with self.app.app_context():
                    job_func(*args, **kwargs)
            except Exception as e:
                print(f"Background job error: {e}")
                import traceback
                traceback.print_exc()
            time.sleep(0.5)

job_queue = BackgroundJobQueue(app)

# ============================================
# DECORATORS
# ============================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'warning')
            next_url = request.url
            return redirect(url_for('login', next=next_url))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# HELPER FUNCTIONS
# ============================================

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

def get_smtp_settings_from_db(user_id):
    settings = db.get_api_settings(user_id)
    if settings:
        d = _row_to_dict(settings)
        return {
            'host': d.get('smtp_host', 'smtp.gmail.com'),
            'port': d.get('smtp_port', 587),
            'user': d.get('smtp_user', ''),
            'password': d.get('smtp_password', ''),
        }
    return None

def get_user_calendly_link(user_id):
    settings = db.get_api_settings(user_id)
    if settings:
        return _row_to_dict(settings).get('meeting_link')
    return None

def generate_tracking_pixel(message_id):
    return f'<img src="/track/open/{message_id}" width="1" height="1" style="display:none;">'

def generate_html_email(body, tracking_pixel):
    lines = body.strip().split('\n')
    html_lines = []

    for line in lines:
        safe = html_module.escape(line)
        if line.startswith('📅') or 'Book a' in line:
            html_lines.append(
                f'<p style="font-size:16px;margin:10px 0;"><strong>{safe}</strong></p>'
            )
        elif 'http' in line and ('calendly' in line or 'meet.google' in line):
            href = html_module.escape(line.strip())
            html_lines.append(
                f'<p style="margin:10px 0;"><a href="{href}" '
                f'style="color:#f97316;text-decoration:none;">{href}</a></p>'
            )
        elif line.strip():
            html_lines.append(f'<p style="margin:5px 0;">{safe}</p>')

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
                   line-height:1.6;color:#333;max-width:600px;margin:0 auto;padding:20px; }}
            .header {{ border-bottom:2px solid #f97316;padding-bottom:10px;margin-bottom:20px; }}
            .content {{ font-size:16px; }}
            .footer {{ margin-top:30px;padding-top:20px;border-top:1px solid #eee;
                      font-size:12px;color:#888;text-align:center; }}
        </style>
    </head>
    <body>
        <div class="header"><h2 style="color:#f97316;">Copywriterflo</h2></div>
        <div class="content">{''.join(html_lines)}</div>
        <div class="footer">
            <p>© 2025 Copywriterflo - Stop chasing clients. Start booking calls.</p>
        </div>
        {tracking_pixel}
    </body>
    </html>
    """
    return html_body

def send_html_email(to_email, subject, html_body, user_id):
    settings = get_smtp_settings_from_db(user_id) if user_id else None
    if not settings or not settings['user'] or not settings['password']:
        print(f"[EMAIL SIMULATED — no SMTP config] To: {to_email} | Subject: {subject}")
        return False, "SMTP not configured"

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = settings['user']
        msg['To'] = to_email
        msg['Subject'] = subject
        plain_text = re.sub(r'<[^>]+>', '', html_body)
        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        if int(settings['port']) == 465:
            server = smtplib.SMTP_SSL(settings['host'], settings['port'])
        else:
            server = smtplib.SMTP(settings['host'], int(settings['port']))
            server.starttls()

        server.login(settings['user'], settings['password'])
        server.send_message(msg)
        server.quit()
        print(f"✅ HTML email sent to {to_email}")
        return True, None
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ SMTP auth error: {e}")
        return False, "Authentication failed — check SMTP credentials"
    except smtplib.SMTPException as e:
        print(f"❌ SMTP error: {e}")
        return False, str(e)
    except Exception as e:
        print(f"❌ Unexpected email error: {e}")
        return False, str(e)

def create_google_meet_link():
    meeting_id = str(uuid.uuid4())[:8]
    return f"https://meet.google.com/{meeting_id}"

# ============================================
# WEBSITE ANALYSIS FUNCTIONS
# ============================================

def fetch_website_content(url):
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching website {url}: {e}")
        return None

def analyze_website_with_ai(website_url, company_name, campaign_industry, user_id):
    client = get_openai_client(user_id)
    if not client:
        return None, None, None, None

    html_content = fetch_website_content(website_url)
    if not html_content:
        return None, None, None, None

    content_preview = html_content[:8000]

    try:
        prompt = f"""You are a website conversion expert. Analyze this website and provide specific recommendations.

Company: {company_name}
Industry: {campaign_industry}
Website: {website_url}

Return your analysis as a JSON object with these exact keys:
- issues (string): List specific problems found
- recommendations (string): Specific actionable recommendations
- personalized_hook (string): A specific observation about their website
- score_reason (string): Why this business needs copywriting help

Website HTML preview:
{content_preview[:8000]}"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a website conversion expert and copywriter. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=800,
        )

        result = response.choices[0].message.content.strip()
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*$', '', result)
        analysis = json.loads(result)

        return (
            str(analysis.get('issues', 'No specific issues identified')),
            str(analysis.get('recommendations', 'Improve website copy and design')),
            str(analysis.get('personalized_hook', f"I noticed {company_name}'s website could use better copywriting")),
            str(analysis.get('score_reason', f"{company_name} needs better website copy")),
        )
    except json.JSONDecodeError as e:
        print(f"Website analysis JSON error: {e}")
        return "Website analysis failed", "Run AI processing again", "Website needs copywriting help", "Standard lead"
    except Exception as e:
        print(f"Website analysis error: {e}")
        return "Website analysis failed", "Run AI processing again", "Website needs copywriting help", "Standard lead"

# ============================================
# GLOBAL BUSINESS SEARCH
# ============================================

OSM_TAG_MAP = {
    'restaurant': [('amenity', 'restaurant')],
    'cafe': [('amenity', 'cafe')],
    'coffee': [('amenity', 'cafe')],
    'coffee shop': [('amenity', 'cafe')],
    'bar': [('amenity', 'bar')],
    'pub': [('amenity', 'pub')],
    'fast food': [('amenity', 'fast_food')],
    'bakery': [('shop', 'bakery')],
    'supermarket': [('shop', 'supermarket')],
    'grocery': [('shop', 'grocery'), ('shop', 'supermarket')],
    'hotel': [('tourism', 'hotel')],
    'hostel': [('tourism', 'hostel')],
    'guesthouse': [('tourism', 'guest_house')],
    'clinic': [('amenity', 'clinic'), ('amenity', 'doctors')],
    'hospital': [('amenity', 'hospital')],
    'pharmacy': [('amenity', 'pharmacy')],
    'dentist': [('amenity', 'dentist')],
    'doctor': [('amenity', 'doctors')],
    'optician': [('shop', 'optician')],
    'lawyer': [('amenity', 'lawyer')],
    'law firm': [('amenity', 'lawyer')],
    'legal': [('amenity', 'lawyer')],
    'attorney': [('amenity', 'lawyer')],
    'accountant': [('office', 'accountant')],
    'bank': [('amenity', 'bank')],
    'insurance': [('office', 'insurance')],
    'shop': [('shop', 'clothes'), ('shop', 'shoes'), ('shop', 'electronics')],
    'clothing': [('shop', 'clothes')],
    'electronics': [('shop', 'electronics')],
    'furniture': [('shop', 'furniture')],
    'salon': [('shop', 'hairdresser')],
    'hair salon': [('shop', 'hairdresser')],
    'beauty salon': [('shop', 'beauty')],
    'barber': [('shop', 'hairdresser')],
    'gym': [('leisure', 'fitness_centre')],
    'fitness': [('leisure', 'fitness_centre')],
    'yoga': [('leisure', 'yoga')],
    'school': [('amenity', 'school')],
    'university': [('amenity', 'university')],
    'college': [('amenity', 'college')],
    'kindergarten': [('amenity', 'kindergarten')],
    'agency': [('office', 'company')],
    'marketing': [('office', 'company')],
    'consulting': [('office', 'consulting')],
    'real estate': [('office', 'estate_agent')],
    'travel': [('shop', 'travel_agency')],
    'car': [('shop', 'car'), ('amenity', 'car_rental')],
    'garage': [('shop', 'car_repair')],
    'vet': [('amenity', 'veterinary')],
    'veterinary': [('amenity', 'veterinary')],
    'church': [('amenity', 'place_of_worship')],
    'mosque': [('amenity', 'place_of_worship')],
    'petrol': [('amenity', 'fuel')],
    'gas station': [('amenity', 'fuel')],
    'fuel': [('amenity', 'fuel')],
    'ecommerce': [('shop', 'general')],
    'e commerce': [('shop', 'general')],
    'online store': [('shop', 'general')],
}

NOMINATIM_CATEGORY_MAP = {
    'restaurant': 'restaurant',
    'cafe': 'cafe',
    'coffee': 'cafe',
    'hotel': 'hotel',
    'lawyer': 'lawyer',
    'law firm': 'lawyer',
    'legal': 'lawyer',
    'attorney': 'lawyer',
    'accountant': 'accountant',
    'bank': 'bank',
    'clinic': 'clinic',
    'hospital': 'hospital',
    'pharmacy': 'pharmacy',
    'salon': 'hair salon',
    'hair salon': 'hair salon',
    'gym': 'fitness centre',
    'fitness': 'fitness centre',
    'school': 'school',
    'university': 'university',
    'supermarket': 'supermarket',
    'grocery': 'supermarket',
    'bakery': 'bakery',
    'consulting': 'consulting',
    'marketing': 'marketing',
    'agency': 'agency',
}

NOMINATIM_HEADERS = {'User-Agent': 'Copywriterflo/2.0 (business-lead-search)'}

def _geocode_location(location: str) -> dict:
    if not location:
        return {}
    while not nominatim_rate_limiter.is_allowed():
        time.sleep(0.2)

    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': location, 'format': 'json', 'limit': 1, 'addressdetails': 1},
            headers=NOMINATIM_HEADERS,
            timeout=10,
        )
        data = resp.json()
        if data:
            place = data[0]
            addr = place.get('address', {})
            return {
                'lat': float(place['lat']),
                'lon': float(place['lon']),
                'country_code': addr.get('country_code', '').lower(),
                'display_name': place.get('display_name', ''),
                'bbox': place.get('boundingbox', []),
            }
    except Exception as e:
        print(f"Geocoding error for '{location}': {e}")
    return {}

def _overpass_search(osm_tags: list, lat: float, lon: float, radius_m: int = 10000, max_results: int = 30) -> list:
    tag_filters = ''
    for key, val in osm_tags:
        tag_filters += f'  node["{key}"="{val}"](around:{radius_m},{lat},{lon});\n'
        tag_filters += f'  way["{key}"="{val}"](around:{radius_m},{lat},{lon});\n'

    overpass_query = f"""
[out:json][timeout:25];
(
{tag_filters}
);
out center tags {max_results};
"""
    try:
        resp = requests.post(
            'https://overpass-api.de/api/interpreter',
            data={'data': overpass_query},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"Overpass returned {resp.status_code}")
            return []

        data = resp.json()
        results = []
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            name = tags.get('name') or tags.get('brand') or ''
            if not name:
                continue

            if element['type'] == 'node':
                el_lat, el_lon = element.get('lat'), element.get('lon')
            else:
                center = element.get('center', {})
                el_lat, el_lon = center.get('lat'), center.get('lon')

            website = tags.get('website') or tags.get('contact:website') or ''
            phone = tags.get('phone') or tags.get('contact:phone') or ''
            city = tags.get('addr:city') or ''
            street = tags.get('addr:street') or ''
            housenumber = tags.get('addr:housenumber') or ''
            address_parts = [p for p in [housenumber, street, city] if p]
            address = ', '.join(address_parts) if address_parts else f"{el_lat:.4f}, {el_lon:.4f}"

            results.append({
                'name': name,
                'company': name,
                'address': address,
                'phone': phone,
                'website': website,
                'rating': 0,
                'total_ratings': 0,
                'place_id': str(element.get('id', '')),
                'category': tags.get('amenity') or tags.get('shop') or tags.get('office') or 'business',
                'source': 'overpass',
            })

        return results
    except Exception as e:
        print(f"Overpass search error: {e}")
        return []

def _nominatim_search(keyword: str, location: str, country_code: str, max_results: int = 20) -> list:
    search_keyword = keyword.lower()
    for bad_term, good_term in NOMINATIM_CATEGORY_MAP.items():
        if bad_term in search_keyword:
            search_keyword = good_term
            break

    clean_location = location.split(',')[0].strip() if location else ''
    queries = [
        f"{search_keyword} {clean_location}",
        f"{search_keyword} in {clean_location}",
    ]

    all_businesses = []
    seen_names: set = set()

    for query in queries:
        if len(all_businesses) >= max_results:
            break

        while not nominatim_rate_limiter.is_allowed():
            time.sleep(0.2)

        params = {
            'q': query,
            'format': 'json',
            'limit': max_results,
            'addressdetails': 1,
            'namedetails': 1,
            'extratags': 1,
            'accept-language': 'en',
        }
        if country_code:
            params['countrycodes'] = country_code

        try:
            resp = requests.get(
                'https://nominatim.openstreetmap.org/search',
                params=params,
                headers=NOMINATIM_HEADERS,
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list):
                continue

            for place in data:
                if not isinstance(place, dict):
                    continue

                name = (place.get('namedetails') or {}).get('name', '')
                if not name:
                    disp = place.get('display_name', '')
                    name = disp.split(',')[0].strip() if disp else ''
                if not name:
                    continue

                norm_name = name.lower()
                if norm_name in seen_names:
                    continue
                seen_names.add(norm_name)

                extratags = place.get('extratags') or {}
                all_businesses.append({
                    'name': name,
                    'company': name,
                    'address': place.get('display_name', ''),
                    'phone': extratags.get('phone', ''),
                    'website': extratags.get('website', ''),
                    'rating': 0,
                    'total_ratings': 0,
                    'place_id': str(place.get('place_id', '')),
                    'category': place.get('type', 'business'),
                    'source': 'nominatim',
                })

                if len(all_businesses) >= max_results:
                    break
        except Exception as e:
            print(f"Nominatim search error for '{query}': {e}")

    return all_businesses

def search_openstreetmap(keyword: str, location: str, max_results: int = 20) -> list:
    geo = _geocode_location(location) if location else {}
    lat = geo.get('lat')
    lon = geo.get('lon')
    country_code = geo.get('country_code', '')

    keyword_lower = keyword.lower().strip()
    all_results = []
    seen_names: set = set()

    if lat and lon:
        osm_tags = []
        for term, tags in OSM_TAG_MAP.items():
            if term in keyword_lower:
                osm_tags = tags
                break

        if not osm_tags:
            osm_tags = [
                ('amenity', '*'), ('shop', '*'), ('office', '*')
            ]
            overpass_query = f"""
[out:json][timeout:25];
(
  node["name"~"{keyword_lower}",i](around:15000,{lat},{lon});
  way["name"~"{keyword_lower}",i](around:15000,{lat},{lon});
);
out center tags {max_results};
"""
            try:
                resp = requests.post(
                    'https://overpass-api.de/api/interpreter',
                    data={'data': overpass_query},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for element in data.get('elements', []):
                        tags = element.get('tags', {})
                        name = tags.get('name', '')
                        if not name or name.lower() in seen_names:
                            continue
                        seen_names.add(name.lower())

                        if element['type'] == 'node':
                            el_lat, el_lon = element.get('lat'), element.get('lon')
                        else:
                            center = element.get('center', {})
                            el_lat, el_lon = center.get('lat'), center.get('lon')

                        website = tags.get('website') or tags.get('contact:website') or ''
                        phone = tags.get('phone') or tags.get('contact:phone') or ''
                        city = tags.get('addr:city') or ''
                        street = tags.get('addr:street') or ''
                        housenumber = tags.get('addr:housenumber') or ''
                        addr_parts = [p for p in [housenumber, street, city] if p]
                        address = ', '.join(addr_parts) if addr_parts else f"{el_lat}, {el_lon}"

                        all_results.append({
                            'name': name,
                            'company': name,
                            'address': address,
                            'phone': phone,
                            'website': website,
                            'rating': 0,
                            'total_ratings': 0,
                            'place_id': str(element.get('id', '')),
                            'category': tags.get('amenity') or tags.get('shop') or tags.get('office') or 'business',
                            'source': 'overpass',
                        })
                        if len(all_results) >= max_results:
                            break
            except Exception as e:
                print(f"Generic Overpass error: {e}")
            osm_tags = []

        if osm_tags:
            overpass_results = _overpass_search(osm_tags, lat, lon, radius_m=15000, max_results=max_results)
            for biz in overpass_results:
                norm = biz['name'].lower()
                if norm not in seen_names:
                    seen_names.add(norm)
                    all_results.append(biz)

    if len(all_results) < max_results:
        nominatim_results = _nominatim_search(keyword, location, country_code, max_results)
        for biz in nominatim_results:
            norm = biz['name'].lower()
            if norm not in seen_names:
                seen_names.add(norm)
                all_results.append(biz)

    return all_results[:max_results]

# ============================================
# AI SEARCH ENHANCEMENT
# ============================================

def enhance_search_with_ai(keyword: str, location: str, user_id: int):
    client = get_openai_client(user_id)
    if not client:
        return keyword, []

    try:
        prompt = f"""Given a user wants to find businesses for copywriting services.

Original Search: "{keyword}" in "{location}"

Please provide:
1. A better search term (more specific business type that OpenStreetMap recognizes)
2. A list of 5 alternative business types that might need copywriting services

Return as JSON:
{{"better_term": "improved search term", "alternative_terms": ["term1", "term2", "term3", "term4", "term5"]}}"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business search optimization expert. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=200,
        )

        result = response.choices[0].message.content.strip()
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*$', '', result)
        analysis = json.loads(result)

        better_term = analysis.get('better_term', keyword).strip() or keyword
        alternatives = analysis.get('alternative_terms', [])
        return better_term, alternatives
    except Exception as e:
        print(f"AI search enhancement error: {e}")
        return keyword, []

def enrich_business_with_ai(business_name: str, business_address: str, user_id: int):
    return {'website': '', 'phone': ''}

# ============================================
# AI SCORING & MESSAGE GENERATION
# ============================================

def generate_lead_score_with_limit(lead_name, lead_company, lead_website, campaign_industry, user_id, website_hook=None):
    if not api_rate_limiter.is_allowed():
        return 5, "Rate limit reached — score deferred"
    return generate_lead_score(lead_name, lead_company, lead_website, campaign_industry, user_id, website_hook)

def generate_lead_score(lead_name, lead_company, lead_website, campaign_industry, user_id, website_hook=None):
    client = get_openai_client(user_id)
    if not client:
        return 5, "OpenAI API key not configured. Please add it in Settings."

    try:
        if website_hook:
            prompt = f"""Score this lead from 1-10 based on how likely they need copywriting services.

Company: {lead_company}
Industry: {campaign_industry}
Website: {lead_website or 'Unknown'}
Website Observation: {website_hook}

Return ONLY: "X - reason" (e.g., "8 - Their website has no CTA, perfect opportunity for copy improvement")"""
        else:
            prompt = f"""Score this lead from 1-10 on how likely they need copywriting services.

Company: {lead_company}
Industry: {campaign_industry}
Website: {lead_website or 'Unknown'}

Return ONLY: "X - reason" (e.g., "8 - E-commerce company with poor product descriptions")"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a lead scoring expert. Return only the score and reason in the specified format."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=80,
        )

        result = response.choices[0].message.content.strip()
        match = re.search(r'(\d+)\s*-\s*(.+)', result)
        if match:
            score = int(match.group(1))
            reason = match.group(2)
        else:
            num_match = re.search(r'(\d+)', result)
            score = int(num_match.group(1)) if num_match else 5
            reason = result
        return max(1, min(10, score)), reason
    except Exception as e:
        print(f"Scoring error: {e}")
        return 5, f"Error: {str(e)[:50]}"

def generate_personalized_message(lead_name, lead_company, campaign_industry, campaign_script, meeting_link, user_id, website_analysis=None, website_hook=None):
    client = get_openai_client(user_id)
    calendly_link = meeting_link or get_user_calendly_link(user_id)

    if not client:
        return f"""Hi {lead_name},

I help businesses like {lead_company} with copywriting in the {campaign_industry} space. Would love to chat!

Best regards,
[Your Name]"""

    try:
        personalization = ""
        if website_hook and website_hook != "None":
            personalization = f"\nSpecific website observation: {website_hook}"
        if website_analysis and website_analysis != "None":
            personalization += f"\n\nWebsite issues identified: {website_analysis[:300]}"

        prompt = f"""Write a short, personalized cold email to a potential copywriting client.

Lead Name: {lead_name}
Company: {lead_company}
Industry: {campaign_industry}
Tone: {campaign_script}
{personalization}

Requirements:
- Be friendly and personal
- Mention their company specifically
- Show you've looked at their business
- Offer specific value based on their website issues
- Ask if they'd be open to a quick 15-min chat
- Include a booking link if available

Email:"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You're a helpful copywriter sending personalized outreach emails."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=350,
        )

        generated_email = response.choices[0].message.content.strip()

        if calendly_link and calendly_link not in generated_email:
            generated_email += f"\n\n📅 **Book a time to chat:** {calendly_link}"

        return generated_email
    except Exception as e:
        print(f"Email generation error: {e}")
        return f"""Hi {lead_name},

I've been following {lead_company} and love what you're doing in the {campaign_industry} space.

I specialise in copywriting that converts. Would you be open to a quick 15-min chat?

Best regards,
[Your Name]"""

def send_confirmation_request(lead, user_id):
    confirmation_token = str(uuid.uuid4())[:16]
    calendly_link = get_user_calendly_link(user_id)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE leads SET confirmation_token = ?, confirmation_sent_at = ? WHERE id = ?',
            (confirmation_token, datetime.now().isoformat(), lead['id']),
        )

    confirm_url = f"{APP_URL}/confirm-meeting/{confirmation_token}"
    decline_url = f"{APP_URL}/decline-meeting/{confirmation_token}"
    subject = f"Quick question about copywriting for {lead['company']}"

    if calendly_link:
        meeting_action = f"👉 **Book your call here:** {calendly_link}"
    else:
        meeting_action = f"""👉 **YES, let's schedule a call**: {confirm_url}
👉 **NO, not right now**: {decline_url}"""

    body = f"""Hi {lead['name']},

Thanks for your interest in my copywriting services!

I'd love to schedule a quick 15-min call to discuss how I can help {lead['company']} with better copy.

{meeting_action}

Looking forward to speaking with you!

Best regards,
Your Copywriting Consultant

---
If you have any questions, just reply to this email."""

    message_id = db.save_message(lead['id'], subject, body)
    tracking_pixel = generate_tracking_pixel(message_id)
    html_body = generate_html_email(body, tracking_pixel)
    send_html_email(lead['email'], subject, html_body, user_id)
    db.mark_email_sent(lead['id'], message_id)

def send_initial_email(lead, personalized_msg, user_id):
    subject = f"Copywriting help for {lead.get('company', 'your business')}"
    message_id = db.save_message(lead['id'], subject, personalized_msg)
    tracking_pixel = generate_tracking_pixel(message_id)
    html_body = generate_html_email(personalized_msg, tracking_pixel)
    success, error = send_html_email(lead['email'], subject, html_body, user_id)

    if success:
        db.mark_email_sent(lead['id'], message_id)
        db.update_lead(lead['id'], status='awaiting_confirmation')
        print(f"📧 Sent initial email to {lead['name']}")
    else:
        print(f"⚠️  Email not sent to {lead['name']}: {error}")
    return success, error

def process_lead_batch(user_id):
    leads = db.get_all_leads_for_processing(user_id)
    api_settings = db.get_api_settings(user_id)
    settings_dict = _row_to_dict(api_settings)

    meeting_link = settings_dict.get('meeting_link', '')
    auto_send_enabled = settings_dict.get('auto_send_enabled', 0)
    auto_send_score = settings_dict.get('auto_send_score', 7)

    init_global_openai_client(user_id)

    for lead in leads:
        try:
            lead_dict = _row_to_dict(lead)
            print(f"\n🔍 Processing lead: {lead_dict.get('name', 'Unknown')}")

            website_hook = None
            website_analysis = None

            if lead_dict.get('website'):
                print(f"🌐 Analysing website: {lead_dict['website']}")
                issues, recommendations, hook, score_reason = analyze_website_with_ai(
                    lead_dict['website'],
                    lead_dict.get('company', ''),
                    lead_dict.get('industry', ''),
                    user_id,
                )
                if hook:
                    website_hook = hook
                    website_analysis = issues
                    db.update_website_analysis(lead_dict['id'], issues or '', recommendations or '', hook or '')
                    print(f"📊 Website analysis complete: {hook[:100]}...")

            score, reason = generate_lead_score_with_limit(
                lead_dict.get('name', ''),
                lead_dict.get('company', ''),
                lead_dict.get('website', ''),
                lead_dict.get('industry', ''),
                user_id,
                website_hook,
            )
            print(f"📊 Score: {score}/10 - {reason}")

            personalized_msg = generate_personalized_message(
                lead_dict.get('name', ''),
                lead_dict.get('company', ''),
                lead_dict.get('industry', ''),
                lead_dict.get('script', ''),
                meeting_link,
                user_id,
                website_analysis,
                website_hook,
            )

            db.update_lead_score(lead_dict['id'], score, reason, personalized_msg)

            if auto_send_enabled and score >= auto_send_score and lead_dict.get('email'):
                job_queue.add_job(send_initial_email, lead_dict, personalized_msg, user_id)

            time.sleep(1)
        except Exception as e:
            print(f"Error processing lead: {e}")
            import traceback
            traceback.print_exc()

# ============================================
# EMAIL REPLY DETECTION
# ============================================

def check_email_replies_background():
    backoff = 120
    max_backoff = 900

    while True:
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT user_id FROM api_settings
                    WHERE smtp_user IS NOT NULL AND smtp_user != ''
                """)
                users = cursor.fetchall()

            for user in users:
                check_and_process_replies(user['user_id'] if hasattr(user, '__getitem__') else user[0])

            backoff = 120
            time.sleep(backoff)
        except Exception as e:
            print(f"Reply check error: {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

def check_and_process_replies(user_id):
    settings = db.get_api_settings(user_id)
    if not settings:
        return

    settings_dict = _row_to_dict(settings)
    smtp_user = settings_dict.get('smtp_user')
    smtp_password = settings_dict.get('smtp_password')

    if not smtp_user or not smtp_password:
        return

    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(smtp_user, smtp_password)
        mail.select("INBOX")

        result, data = mail.search(None, '(UNSEEN)')
        if result != 'OK' or not data[0]:
            return

        for num in data[0].split():
            try:
                result, msg_data = mail.fetch(num, "(RFC822)")
                if result != 'OK':
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                from_email = email.utils.parseaddr(msg['From'])[1]

                if from_email == smtp_user:
                    mail.store(num, '+FLAGS', '\\Seen')
                    continue

                lead = find_lead_by_email(from_email, user_id)
                if not lead:
                    mail.store(num, '+FLAGS', '\\Seen')
                    continue

                body = extract_email_body(msg)
                mail.store(num, '+FLAGS', '\\Seen')
                process_lead_reply(lead, body, user_id)
            except Exception as e:
                print(f"Error processing individual email: {e}")
    except imaplib.IMAP4.error as e:
        print(f"IMAP error for user {user_id}: {e}")
    except Exception as e:
        print(f"Error checking replies for user {user_id}: {e}")
    finally:
        if mail:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

def find_lead_by_email(email_address, user_id):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.*, c.name as campaign_name, c.industry, c.user_id
            FROM leads l
            JOIN campaigns c ON l.campaign_id = c.id
            WHERE l.email = ? AND c.user_id = ?
        """, (email_address, user_id))
        result = cursor.fetchone()
        if result:
            return _row_to_dict(result)
    return None

def extract_email_body(msg):
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if content_type == "text/plain" and "attachment" not in content_disposition:
                for encoding in ('utf-8', 'latin-1', 'ascii'):
                    try:
                        body = part.get_payload(decode=True).decode(encoding, errors='ignore')
                        break
                    except Exception:
                        pass
                if body:
                    break
    else:
        for encoding in ('utf-8', 'latin-1', 'ascii'):
            try:
                body = msg.get_payload(decode=True).decode(encoding, errors='ignore')
                break
            except Exception:
                pass
        if not body:
            body = str(msg.get_payload())

    lines = body.split('\n')
    cleaned = []
    for line in lines:
        if line.startswith('>'):
            continue
        stripped = line.strip()
        if stripped in ('--', 'Sent from') or 'wrote:' in line:
            break
        if not cleaned and not stripped:
            continue
        cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    return (result[:1000] + "...") if len(result) > 1000 else (result or "[No text content in email]")

def process_lead_reply(lead, reply_body, user_id):
    client = get_openai_client(user_id)
    if not client:
        print(f"No OpenAI client for user {user_id}")
        return

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": """Analyze this email reply from a potential copywriting client.
Classify into exactly one of these categories:
- HOT: They want to schedule a call/meeting immediately
- INTERESTED: They're interested but want more info
- MAYBE: They want pricing or to check back later
- NOT_INTERESTED: They said no or not now
- QUESTION: They asked a specific question

Return your analysis as a JSON object with these keys:
{"category": "HOT/INTERESTED/MAYBE/NOT_INTERESTED/QUESTION", "reason": "brief explanation", "extracted_info": "any specific dates, times, or questions mentioned"}"""},
                {"role": "user", "content": f"Lead Name: {lead['name']}\nCompany: {lead['company']}\nTheir Reply: {reply_body}"},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        result = response.choices[0].message.content.strip()
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*$', '', result)
        analysis = json.loads(result)
        category = analysis.get('category', 'MAYBE')
        reason = analysis.get('reason', '')

        with db.get_connection() as conn:
            cursor = conn.cursor()

            if category == "HOT":
                calendly_link = get_user_calendly_link(user_id)
                if calendly_link:
                    meeting_action = f"👉 **Book your call here:** {calendly_link}"
                    reply_email_body = f"""Hi {lead['name']},

Great! Let's get a call scheduled.

{meeting_action}

I look forward to our conversation!

Best regards,
Your Copywriting Consultant"""
                else:
                    meeting_link = create_google_meet_link()
                    meeting_time = (datetime.now() + timedelta(days=1)).replace(
                        hour=10, minute=0, second=0, microsecond=0
                    )
                    db.mark_meeting_scheduled(lead['id'], meeting_link, meeting_time.isoformat())
                    reply_email_body = f"""Hi {lead['name']},

Great! Your meeting has been scheduled for {meeting_time.strftime('%B %d, %Y at %I:%M %p')}.

Join the Google Meet here: {meeting_link}

I look forward to our conversation!

Best regards,
Your Copywriting Consultant"""

                send_html_email(
                    lead['email'], "Meeting Confirmation",
                    generate_html_email(reply_email_body, ''), user_id,
                )
                cursor.execute("""
                    UPDATE leads SET replied=1, status='meeting_scheduled', notes=? WHERE id=?
                """, (f"HOT reply: {reply_body[:500]}\nAI Analysis: {reason}", lead['id']))
                print(f"🔥 {lead['name']} is HOT — scheduled meeting")
            elif category == "INTERESTED":
                cursor.execute("""
                    UPDATE leads SET replied=1, status='interested', notes=? WHERE id=?
                """, (f"Interested reply: {reply_body[:500]}\nAI Analysis: {reason}", lead['id']))
                print(f"📝 {lead['name']} is interested — follow up needed")
            elif category == "NOT_INTERESTED":
                cursor.execute("""
                    UPDATE leads SET replied=1, status='not_interested', notes=? WHERE id=?
                """, (f"Not interested: {reply_body[:500]}", lead['id']))
                print(f"❌ {lead['name']} is not interested")
            elif category == "QUESTION":
                q_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful copywriter. Answer the client's question briefly and professionally."},
                        {"role": "user", "content": f"Client Question: {reply_body}\n\nWrite a brief, helpful response (max 100 words)."},
                    ],
                    max_tokens=200,
                )
                answer = q_response.choices[0].message.content.strip()
                send_html_email(lead['email'], "Answering your question", generate_html_email(answer, ''), user_id)
                cursor.execute("""
                    UPDATE leads SET replied=1, status='question_answered', notes=? WHERE id=?
                """, (f"Question: {reply_body[:500]}\nAnswer sent: {answer[:200]}", lead['id']))
                print(f"❓ Answered question from {lead['name']}")
            else:
                cursor.execute("""
                    UPDATE leads SET replied=1, status='follow_up_needed', notes=? WHERE id=?
                """, (f"Reply: {reply_body[:500]}\nAI Analysis: {reason}", lead['id']))
                print(f"🔄 {lead['name']} needs follow-up — {reason}")

            conn.commit()

        message_id = db.save_message(lead['id'], f"Reply from {lead['name']}", reply_body)
        db.mark_replied(lead['id'], message_id)

        user = db.get_user(user_id)
        if user and _row_to_dict(user).get('email'):
            user_dict = _row_to_dict(user)
            notification_body = f"""Lead: {lead['name']}
Company: {lead['company']}
Category: {category}
Reply: {reply_body[:200]}

Login to your dashboard to see full details and take action."""
            send_html_email(
                user_dict['email'],
                f"📬 Lead Reply: {lead['name']} - {category}",
                generate_html_email(notification_body, ''),
                user_id,
            )
    except json.JSONDecodeError as e:
        print(f"Reply analysis JSON error: {e}")
    except Exception as e:
        print(f"Error processing reply: {e}")

# ============================================
# STRIPE PAYMENT ROUTES
# ============================================

@app.route('/pricing')
def pricing():
    has_access = False
    payment_info = None
    
    if 'user_id' in session:
        has_access = user_has_lifetime_access(session['user_id'])
        payment_info = get_payment_status(session['user_id'])
    
    display_price = CAMPAIGN_PRICE / 100
    
    return render_template('pricing.html', 
                         price=display_price,
                         currency=CURRENCY.upper(),
                         has_access=has_access,
                         payment_info=payment_info,
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe checkout session for lifetime access"""
    user = db.get_user(session['user_id'])
    user_dict = _row_to_dict(user)
    email = user_dict.get('email')
    
    if not email:
        return jsonify({'error': 'Please add your email address in settings first'}), 400
    
    success_url = f"{APP_URL}/payment-success"
    cancel_url = f"{APP_URL}/payment-cancel"
    
    print(f"💰 Creating Stripe checkout for user {session['user_id']}")
    print(f"   Success URL: {success_url}")
    print(f"   Cancel URL: {cancel_url}")
    
    session_id, checkout_url = create_payment_session(
        session['user_id'],
        email,
        success_url,
        cancel_url
    )
    
    if checkout_url:
        session['payment_session_id'] = session_id
        return jsonify({'sessionId': session_id, 'url': checkout_url})
    else:
        return jsonify({'error': 'Failed to create checkout session. Please check Stripe configuration.'}), 500

@app.route('/payment-success')
def payment_success():
    """Payment success page - verify and grant access"""
    session_id = request.args.get('session_id')
    
    print(f"💰 Payment success callback received")
    print(f"   Session ID: {session_id}")
    print(f"   Session user_id: {session.get('user_id')}")
    
    if not session_id and 'payment_session_id' in session:
        session_id = session['payment_session_id']
    
    if session_id:
        # Verify the payment
        success = handle_successful_payment(session_id)
        
        if success:
            # Get user_id from session or from the payment
            user_id = session.get('user_id')
            if user_id:
                db.grant_lifetime_access(user_id)
                flash('Payment successful! You now have LIFETIME access to all features. Create unlimited campaigns! 🎉', 'success')
            else:
                flash('Payment successful! Please login to access your account.', 'success')
        else:
            flash('Payment verification failed. Please contact support.', 'error')
    else:
        flash('Payment session not found.', 'error')
    
    if 'payment_session_id' in session:
        del session['payment_session_id']
    
    return redirect(url_for('dashboard'))

@app.route('/payment-cancel')
def payment_cancel():
    """Payment cancelled page"""
    if 'payment_session_id' in session:
        del session['payment_session_id']
    
    flash('Payment cancelled. You can purchase lifetime access when ready.', 'warning')
    return redirect(url_for('pricing'))

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    if not webhook_secret:
        print("⚠️ Webhook secret not configured. Skipping signature verification.")
        try:
            event = json.loads(payload)
        except:
            return jsonify({'error': 'Invalid payload'}), 400
    else:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError:
            return jsonify({'error': 'Invalid payload'}), 400
        except stripe.error.SignatureVerificationError:
            return jsonify({'error': 'Invalid signature'}), 400
    
    if event['type'] == 'checkout.session.completed':
        session_data = event['data']['object']
        session_id = session_data['id']
        metadata = session_data.get('metadata', {})
        
        user_id = int(metadata.get('user_id', 0))
        
        if user_id:
            handle_successful_payment(session_id)
            db.grant_lifetime_access(user_id)
            print(f"✅ Webhook: Lifetime access granted to user {user_id}")
    
    return jsonify({'status': 'success'}), 200

# ============================================
# HEALTH CHECK ENDPOINT
# ============================================

@app.route('/health')
def health_check():
    """Health check endpoint for uptime monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': 'postgresql' if db.use_postgres else 'sqlite',
        'version': '1.0.0'
    }), 200

# ============================================
# MEETING MANAGEMENT ROUTES
# ============================================

@app.route('/meetings')
@login_required
def meetings():
    user_id = session['user_id']

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, l.company, l.email, l.phone,
                   l.meeting_link, l.meeting_time, l.status,
                   c.name as campaign_name
            FROM leads l
            JOIN campaigns c ON l.campaign_id = c.id
            WHERE c.user_id = ? AND (l.meeting_scheduled = 1 OR l.status = 'calendly_sent')
            ORDER BY
                CASE WHEN l.meeting_time IS NOT NULL THEN l.meeting_time ELSE '9999-12-31' END ASC
        """, (user_id,))
        rows = cursor.fetchall()

    meetings_list = [
        {
            'id': r[0], 'name': r[1], 'company': r[2], 'email': r[3],
            'phone': r[4], 'meeting_link': r[5], 'meeting_time': r[6],
            'status': r[7], 'campaign_name': r[8],
        }
        for r in rows
    ]
    return render_template('meetings.html', meetings=meetings_list)

@app.route('/meeting/<int:lead_id>/reschedule', methods=['POST'])
@login_required
def reschedule_meeting(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        return jsonify({'error': 'Permission denied'}), 403

    new_time_str = request.json.get('meeting_time')
    if not new_time_str:
        return jsonify({'error': 'No meeting time provided'}), 400

    try:
        new_time = datetime.fromisoformat(new_time_str.replace(' ', 'T'))
    except ValueError:
        return jsonify({'error': 'Invalid time format. Use YYYY-MM-DD HH:MM'}), 400

    db.update_lead(lead_id, meeting_time=new_time.isoformat())
    lead_dict = _row_to_dict(lead)

    if lead_dict.get('email'):
        body = f"""Hi {lead_dict['name']},

Your meeting has been rescheduled to {new_time.strftime('%B %d, %Y at %I:%M %p')}.

Join link: {lead_dict['meeting_link']}

If this doesn't work for you, please let me know.

Best regards,
Your Copywriting Consultant"""
        send_html_email(lead_dict['email'], "Meeting Rescheduled", generate_html_email(body, ''), session['user_id'])

    return jsonify({'success': True, 'message': 'Meeting rescheduled'})

@app.route('/meeting/<int:lead_id>/cancel', methods=['POST'])
@login_required
def cancel_meeting(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        return jsonify({'error': 'Permission denied'}), 403

    db.update_lead(lead_id, meeting_scheduled=0, meeting_link=None, meeting_time=None, status='cancelled')
    lead_dict = _row_to_dict(lead)

    if lead_dict.get('email'):
        body = f"""Hi {lead_dict['name']},

Our meeting has been cancelled.

Feel free to reschedule at any time by replying to this email.

Best regards,
Your Copywriting Consultant"""
        send_html_email(lead_dict['email'], "Meeting Cancelled", generate_html_email(body, ''), session['user_id'])

    return jsonify({'success': True, 'message': 'Meeting cancelled'})

# ============================================
# ROUTES - PUBLIC
# ============================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user_email = request.form.get('email', '').strip()

        if not username or not password:
            flash('Username and password are required', 'error')
            return redirect(url_for('register'))

        existing = db.get_user_by_username(username)
        if existing:
            flash('Username already exists', 'error')
            return redirect(url_for('register'))

        hashed_pw = hash_password(password)
        db.create_user(username, hashed_pw, user_email)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next', url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.get_user_by_username(username)
        if user and verify_password(password, user['password']):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session.permanent = True
            init_global_openai_client(user['id'])
            flash('Login successful!', 'success')
            return redirect(next_url)

        flash('Invalid credentials', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    session.clear()
    if user_id and user_id in _openai_clients:
        del _openai_clients[user_id]
    flash('Logged out', 'success')
    return redirect(url_for('index'))

# ============================================
# CONFIRMATION ROUTES
# ============================================

@app.route('/confirm-meeting/<token>')
def confirm_meeting(token):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name FROM leads WHERE confirmation_token = ?", (token,))
        lead = cursor.fetchone()

        if not lead:
            return "Invalid or expired link", 404

        lead_id, lead_email, lead_name = lead['id'], lead['email'], lead['name']
        meeting_link = create_google_meet_link()
        meeting_time = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

        cursor.execute("""
            UPDATE leads SET meeting_scheduled=1, meeting_link=?, meeting_time=?, status='meeting_scheduled'
            WHERE id=?
        """, (meeting_link, meeting_time.isoformat(), lead_id))
        conn.commit()

    subject = "Meeting Confirmed - Copywriting Consultation"
    body = f"""Hi {lead_name},

Great! Your meeting has been confirmed for {meeting_time.strftime('%B %d, %Y at %I:%M %p')}.

Join the Google Meet here: {meeting_link}

Please add this to your calendar.

I look forward to our conversation!

Best regards,
Your Copywriting Consultant"""

    send_html_email(lead_email, subject, generate_html_email(body, ''), None)
    return render_template('confirmation.html', meeting_link=meeting_link, meeting_time=meeting_time)

@app.route('/decline-meeting/<token>')
def decline_meeting(token):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE leads SET status='declined' WHERE confirmation_token=?", (token,))
        conn.commit()
    return render_template('declined.html')

# ============================================
# ROUTES - SETTINGS
# ============================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = db.get_user(session['user_id'])
    api_settings = db.get_api_settings(session['user_id'])
    notification_settings = db.get_notification_settings(session['user_id'])

    api_dict = _row_to_dict(api_settings)
    notif_dict = _row_to_dict(notification_settings)
    user_dict = _row_to_dict(user)

    if request.method == 'POST':
        openai_api_key = request.form.get('openai_api_key', '').strip()

        db.update_api_settings(
            session['user_id'],
            openai_api_key=openai_api_key,
            openai_model=request.form.get('openai_model', 'gpt-3.5-turbo'),
            smtp_host=request.form.get('smtp_host', 'smtp.gmail.com'),
            smtp_port=int(request.form.get('smtp_port', 587)),
            smtp_user=request.form.get('smtp_user', ''),
            smtp_password=request.form.get('smtp_password', ''),
            auto_send_enabled=1 if request.form.get('auto_send_enabled') else 0,
            auto_send_score=int(request.form.get('auto_send_score', 7)),
            meeting_link=request.form.get('meeting_link', ''),
            google_meet_enabled=1 if request.form.get('google_meet_enabled') else 0,
        )

        if session['user_id'] in _openai_clients:
            del _openai_clients[session['user_id']]
        init_global_openai_client(session['user_id'])

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET phone=?, whatsapp_number=?, telegram_chat_id=? WHERE id=?',
                (
                    request.form.get('phone', ''),
                    request.form.get('whatsapp_number', ''),
                    request.form.get('telegram_chat_id', ''),
                    session['user_id'],
                ),
            )

        db.update_notification_settings(
            session['user_id'],
            email_enabled=request.form.get('email_enabled') == 'on',
            sms_enabled=request.form.get('sms_enabled') == 'on',
            whatsapp_enabled=request.form.get('whatsapp_enabled') == 'on',
            telegram_enabled=request.form.get('telegram_enabled') == 'on',
        )

        flash('Settings saved successfully!', 'success')
        return redirect(url_for('settings'))

    return render_template('settings.html', user=user_dict, api_settings=api_dict, notification_settings=notif_dict)

# ============================================
# ROUTES - DASHBOARD & CAMPAIGNS
# ============================================

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.get_user(session['user_id'])
    campaigns = db.get_user_campaigns(session['user_id'])

    stats = []
    total_leads = total_hot = total_sent = total_replies = total_meetings = total_websites_analyzed = 0

    for campaign in campaigns:
        campaign_stats = db.get_campaign_stats(campaign['id'])
        campaign_stats['name'] = campaign['name']
        campaign_stats['id'] = campaign['id']
        stats.append(campaign_stats)
        total_leads += campaign_stats['total_leads']
        total_hot += campaign_stats['hot_leads']
        total_sent += campaign_stats['messages_sent']
        total_replies += campaign_stats['replies']
        total_meetings += campaign_stats['meetings']
        total_websites_analyzed += campaign_stats.get('websites_analyzed', 0)

    return render_template(
        'dashboard.html',
        user=_row_to_dict(user),
        campaigns=campaigns,
        stats=stats,
        total_leads=total_leads,
        total_hot=total_hot,
        total_sent=total_sent,
        total_replies=total_replies,
        total_meetings=total_meetings,
        total_websites_analyzed=total_websites_analyzed,
    )

@app.route('/campaign/new', methods=['GET', 'POST'])
@login_required
@require_payment
def campaign_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        industry = request.form.get('industry', '').strip()
        script = request.form.get('script', '').strip()
        location = request.form.get('location', '').strip()

        if not name:
            flash('Campaign name is required', 'error')
            return redirect(url_for('campaign_new'))

        campaign_id = db.create_campaign(session['user_id'], name, industry, script, location)
        flash('Campaign created! Now add your leads.', 'success')
        return redirect(url_for('leads_upload', campaign_id=campaign_id))

    return render_template('campaign_new.html')

@app.route('/campaign/<int:campaign_id>')
@login_required
def campaign_detail(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('dashboard'))

    leads = db.get_campaign_leads(campaign_id)
    stats = db.get_campaign_stats(campaign_id)
    return render_template('campaign_detail.html', campaign=campaign, leads=leads, stats=stats)

@app.route('/campaign/<int:campaign_id>/delete', methods=['POST'])
@login_required
def campaign_delete(campaign_id):
    db.delete_campaign(campaign_id)
    flash('Campaign deleted', 'success')
    return redirect(url_for('dashboard'))

# ============================================
# ROUTES - AI-POWERED BUSINESS SEARCH
# ============================================

@app.route('/campaign/<int:campaign_id>/business-search', methods=['GET', 'POST'])
@login_required
@require_payment
def business_search(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('dashboard'))

    results = []
    alternative_terms = []

    if request.method == 'POST':
        keyword = request.form.get('keyword', '').strip()
        location = request.form.get('location', '').strip()
        max_results = min(int(request.form.get('max_results', 20)), 50)
        use_ai = request.form.get('use_ai') == 'on'

        if keyword:
            if use_ai:
                flash('🤖 AI is analysing and enhancing your search…', 'info')
                better_term, alternatives = enhance_search_with_ai(keyword, location, session['user_id'])
                alternative_terms = alternatives
                if better_term and better_term.lower() != keyword.lower():
                    flash(f'💡 AI suggests using "{better_term}" for better results', 'info')
                    keyword = better_term

            flash(f'🔍 Searching for "{keyword}" in "{location or "worldwide"}"…', 'info')
            results = search_openstreetmap(keyword, location, max_results)

            flash(f'✅ Found {len(results)} businesses', 'success')
            db.save_business_search(session['user_id'], campaign_id, keyword, location, len(results))

            if len(results) == 0 and alternative_terms:
                flash(f'💡 Try searching for: {", ".join(alternative_terms[:3])}', 'info')

    searches = db.get_business_searches(campaign_id)
    return render_template(
        'business_search.html',
        campaign=campaign,
        results=results,
        searches=searches,
        alternative_terms=alternative_terms,
    )

@app.route('/campaign/<int:campaign_id>/import-business-leads', methods=['POST'])
@login_required
def import_business_leads(campaign_id):
    data = request.get_json()
    businesses = data.get('businesses', [])

    if not businesses:
        return jsonify({'error': 'No businesses to import'}), 400

    leads_data = []
    for biz in businesses:
        lead = {
            'name': biz.get('name', ''),
            'company': biz.get('company', biz.get('name', '')),
            'email': '',
            'website': biz.get('website', ''),
            'phone': biz.get('phone', ''),
            'address': biz.get('address', ''),
            'rating': biz.get('rating', 0),
            'total_ratings': biz.get('total_ratings', 0),
            'place_id': biz.get('place_id', ''),
        }
        if lead['name']:
            leads_data.append(lead)

    count = db.add_leads(campaign_id, leads_data)
    job_queue.add_job(process_lead_batch, session['user_id'])
    return jsonify({
        'success': True,
        'count': count,
        'message': f'Imported {count} leads! AI analysis started.',
    })

# ============================================
# ROUTES - LEADS
# ============================================

@app.route('/campaign/<int:campaign_id>/upload-leads', methods=['GET', 'POST'])
@login_required
def leads_upload(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        if 'csv_file' in request.files:
            file = request.files['csv_file']
            if file and file.filename.endswith('.csv'):
                try:
                    content = file.read().decode('utf-8-sig')
                    csv_reader = csv.DictReader(io.StringIO(content))
                    leads_data = []
                    for row in csv_reader:
                        lead = {
                            'name': row.get('name') or row.get('Name', ''),
                            'email': row.get('email') or row.get('Email', ''),
                            'company': row.get('company') or row.get('Company', ''),
                            'website': row.get('website') or row.get('Website', ''),
                            'phone': row.get('phone') or row.get('Phone', ''),
                        }
                        if lead['name']:
                            leads_data.append(lead)
                    count = db.add_leads(campaign_id, leads_data)
                    flash(f'Added {count} leads! Starting AI analysis…', 'success')
                    job_queue.add_job(process_lead_batch, session['user_id'])
                    return redirect(url_for('campaign_detail', campaign_id=campaign_id))
                except Exception as e:
                    flash(f'Error reading CSV: {e}', 'error')

        name = request.form.get('name', '').strip()
        if name:
            db.add_leads(campaign_id, [{
                'name': name,
                'email': request.form.get('email', ''),
                'company': request.form.get('company', ''),
                'website': request.form.get('website', ''),
                'phone': request.form.get('phone', ''),
            }])
            flash('Lead added!', 'success')

    return render_template('leads_upload.html', campaign=campaign)

@app.route('/campaign/<int:campaign_id>/process', methods=['POST'])
@login_required
def process_campaign(campaign_id):
    flash('AI processing started! Website analysis and lead scoring in progress.', 'success')
    job_queue.add_job(process_lead_batch, session['user_id'])
    return redirect(url_for('campaign_detail', campaign_id=campaign_id))

@app.route('/check-replies', methods=['POST'])
@login_required
def check_replies():
    flash('Checking for email replies…', 'info')
    return jsonify({'status': 'checking_replies'})

@app.route('/lead/<int:lead_id>')
@login_required
def lead_detail(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        flash('Lead not found', 'error')
        return redirect(url_for('dashboard'))

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        flash('You do not have permission to view this lead', 'error')
        return redirect(url_for('dashboard'))

    messages = db.get_lead_messages(lead_id)
    settings = db.get_api_settings(session['user_id'])

    return render_template(
        'lead_detail.html',
        lead=_row_to_dict(lead),
        messages=messages,
        settings=_row_to_dict(settings),
    )

@app.route('/lead/<int:lead_id>/send', methods=['POST'])
@login_required
def lead_send(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        return jsonify({'error': 'Permission denied'}), 403

    lead_dict = _row_to_dict(lead)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data received'}), 400

    subject = data.get('subject', 'Copywriting services for your business')
    content = data.get('content', lead_dict.get('personalized_message', ''))

    if not content:
        return jsonify({'error': 'No message content'}), 400
    if not lead_dict.get('email'):
        return jsonify({'error': 'No email address'}), 400
    if not email_rate_limiter.is_allowed():
        return jsonify({'error': 'Rate limit exceeded. Please wait before sending more emails.'}), 429

    message_id = db.save_message(lead_id, subject, content)
    tracking_pixel = generate_tracking_pixel(message_id)
    html_body = generate_html_email(content, tracking_pixel)
    success, error = send_html_email(lead_dict['email'], subject, html_body, session['user_id'])

    if success:
        db.mark_email_sent(lead_id, message_id)
        return jsonify({'success': True, 'message': 'Email sent!'})
    else:
        return jsonify({'error': error or 'Failed to send email'}), 500

@app.route('/lead/<int:lead_id>/send-confirmation', methods=['POST'])
@login_required
def send_confirmation(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        return jsonify({'error': 'Permission denied'}), 403

    send_confirmation_request(_row_to_dict(lead), session['user_id'])
    db.update_lead(lead_id, status='confirmation_sent')
    return jsonify({'success': True, 'message': 'Confirmation request sent!'})

@app.route('/lead/<int:lead_id>/schedule-meeting', methods=['POST'])
@login_required
def schedule_meeting(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    campaign = db.get_campaign(lead['campaign_id'])
    if campaign['user_id'] != session['user_id']:
        return jsonify({'error': 'Permission denied'}), 403

    lead_dict = _row_to_dict(lead)
    calendly_link = get_user_calendly_link(session['user_id'])

    if calendly_link:
        meeting_link = calendly_link
        meeting_time = None
        db.update_lead(lead_id, status='calendly_sent')
    else:
        meeting_link = create_google_meet_link()
        meeting_time = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        db.mark_meeting_scheduled(lead_id, meeting_link, meeting_time.isoformat())

    db.update_lead(lead_id, status='meeting_scheduled')

    if lead_dict.get('email'):
        if calendly_link:
            body = f"""Hi {lead_dict.get('name')},

You can book your copywriting consultation here: {calendly_link}

I look forward to speaking with you!

Best regards,
Your Copywriting Consultant"""
        else:
            body = f"""Hi {lead_dict.get('name')},

Your meeting has been scheduled for {meeting_time.strftime('%B %d, %Y at %I:%M %p')}.

Join the Google Meet here: {meeting_link}

I look forward to speaking with you!

Best regards,
Your Copywriting Consultant"""

        send_html_email(lead_dict['email'], "Copywriting Consultation", generate_html_email(body, ''), session['user_id'])

    return jsonify({
        'success': True,
        'meeting_link': meeting_link,
        'meeting_time': meeting_time.isoformat() if meeting_time else None,
        'calendly': bool(calendly_link),
    })

# ============================================
# ROUTES - UTILITY
# ============================================

@app.route('/track/open/<int:message_id>')
def track_open(message_id):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT lead_id FROM messages WHERE id=?', (message_id,))
        result = cursor.fetchone()
        if result:
            cursor.execute('UPDATE leads SET opened=1 WHERE id=?', (result['lead_id'],))
            cursor.execute('UPDATE messages SET opened_at=? WHERE id=?', (datetime.now().isoformat(), message_id))

    pixel = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
    return send_file(io.BytesIO(pixel), mimetype='image/gif', as_attachment=False, download_name='pixel.gif')

@app.route('/download-csv-template')
@login_required
def download_csv_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'email', 'company', 'website', 'phone'])
    writer.writerow(['John Doe', 'john@example.com', 'Example Corp', 'https://example.com', '+1234567890'])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='leads_template.csv',
    )

@app.route('/api/campaign-stats/<int:campaign_id>')
@login_required
def api_campaign_stats(campaign_id):
    stats = db.get_campaign_stats(campaign_id)
    return jsonify(stats)

# ============================================
# RUN APP
# ============================================

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)

    reply_thread = threading.Thread(target=check_email_replies_background, daemon=True)
    reply_thread.start()
    print("✅ Reply checker background thread started")

    print("=" * 60)
    print("⚡ Copywriterflo - Copywriter Acquisition System")
    print("=" * 60)
    print(f"✅ App URL: {APP_URL}")
    print("✅ Database: copywriter.db")
    print("✅ CSRF Protection: Enabled")
    print("✅ Rate Limiting: Enabled (incl. Nominatim 1 req/s)")
    print("✅ HTML Emails: Enabled (XSS-safe)")
    print("✅ Tracking Pixel: Enabled")
    print("✅ Background Queue: Enabled (race-condition fixed)")
    print("✅ AI-Powered Business Search: Global (Overpass + Nominatim)")
    print("✅ AI Website Analysis: Ready")
    print("✅ Email Reply Detection: Ready (exponential back-off)")
    print("✅ Meeting Management: Ready")
    print("✅ Per-user OpenAI client cache: Enabled")
    print("✅ Stripe Payment Integration: One-time $280 Lifetime Access")
    print("=" * 60)
    print("🌐 Server running at: http://localhost:5000")
    print("📱 Access via ngrok: " + APP_URL)
    print("📱 Login with your registered account")
    print("⚡ Press Ctrl+C to stop")
    print("=" * 60)

    app.run(debug=True, host='0.0.0.0', port=5000)