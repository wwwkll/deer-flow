import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

base_url = 'http://192.168.31.187:1234/v1'

try:
    resp = httpx.get(f'{base_url}/models', timeout=10)
    data = resp.json()
    print('=== Available Models ===')
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f'Error: {e}')
