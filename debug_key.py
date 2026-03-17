"""Debug script to check API key and test raw request."""
import os
import hashlib
import hmac
import time
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_API_SECRET", "")

print(f"API Key length: {len(api_key)}")
print(f"API Key first 12: '{api_key[:12]}'")
print(f"API Key last 4: '{api_key[-4:]}'")
print(f"API Secret length: {len(api_secret)}")
print(f"API Key repr: {repr(api_key[:20])}...")
print()

# Check for hidden characters
if api_key != api_key.strip():
    print("WARNING: API key has leading/trailing whitespace!")
if api_secret != api_secret.strip():
    print("WARNING: API secret has leading/trailing whitespace!")

# Check for BOM
if api_key.startswith('\ufeff'):
    print("WARNING: API key starts with BOM character!")

# Test raw request
base_url = "https://demo-fapi.binance.com"
timestamp = int(time.time() * 1000)
params = f"timestamp={timestamp}"
signature = hmac.new(
    api_secret.encode("utf-8"),
    params.encode("utf-8"),
    hashlib.sha256,
).hexdigest()

url = f"{base_url}/fapi/v2/balance?{params}&signature={signature}"
headers = {"X-MBX-APIKEY": api_key}

print(f"Request URL: {url}")
print(f"Header API Key: '{headers['X-MBX-APIKEY'][:20]}...'")
print()

resp = requests.get(url, headers=headers, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")
