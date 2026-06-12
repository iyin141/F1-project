import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

print("--- Proxy Configuration Test ---")

# Import the runtime which contains our proxy setup logic
try:
    import api.session.runtime
except ImportError:
    # If run outside the standard python path, append the current dir
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import api.session.runtime

import requests

def test_proxy():
    http_proxy = os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('HTTPS_PROXY')
    
    print("\n1. Environment Variables Set:")
    print(f"HTTP_PROXY:  {http_proxy}")
    print(f"HTTPS_PROXY: {https_proxy}")
    
    if not https_proxy:
        print("\n❌ [FAIL] Proxy variables are not set. Please ensure PROXY_HOST, PROXY_USER, etc., are in your .env file.")
        return

    print("\n2. Testing connection through proxy...")
    try:
        # Webshare proxies sometimes fail on plain HTTP or httpbin, so we use api.ipify.org over HTTPS
        response = requests.get("https://api.ipify.org?format=json", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print("\n✅ [SUCCESS] Connection established through proxy!")
        print(f"🌐 IP Address seen by the internet: {data.get('ip')}")
        print("\n(If this IP is different from your Oracle VM's IP, your rotating residential proxy is working perfectly!)")
        
    except requests.exceptions.ProxyError as e:
        print("\n❌ [FAIL] Proxy Authentication or Connection Failed.")
        print("Check if your PROXY_USER, PROXY_PASS, and PROXY_HOST are correct in .env.")
        print(f"Error Details: {e}")
    except requests.exceptions.ConnectTimeout:
        print("\n❌ [FAIL] Connection timed out. The proxy server is not responding.")
    except Exception as e:
        print(f"\n❌ [FAIL] Request failed with an unexpected error: {e}")

if __name__ == "__main__":
    test_proxy()
