import os
import requests
import logging
from urllib.request import getproxies

logging.basicConfig(level=logging.DEBUG)

proxy_user = "wjzadxmv-1"
proxy_pass = "ejx6lr93ljd6"
proxy_host = "p.webshare.io"
proxy_port = "80" # Let's match your curl test

proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"

os.environ['HTTPS_PROXY'] = proxy_url
os.environ['HTTP_PROXY'] = proxy_url

print(f"Testing requests via proxy: {proxy_url.replace(proxy_pass, '***')}")
print(f"System proxies detected: {getproxies()}")

url = "https://livetiming.formula1.com/static/2025/2025-10-19_United_States_Grand_Prix/2025-10-19_Race/SessionInfo.jsonStream"

try:
    response = requests.get(url, timeout=10)
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    print(f"Body snippet: {response.text[:200]}")
except Exception as e:
    print(f"\nRequest failed: {type(e).__name__}: {str(e)}")
