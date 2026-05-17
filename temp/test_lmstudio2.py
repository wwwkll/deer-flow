import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'http://192.168.31.187:1234/v1/chat/completions'
payload = {
    'model': 'qwen3.6-27b',
    'messages': [{'role': 'user', 'content': '1+1=?'}],
    'max_tokens': 500,
    'stream': False
}
headers = {'Content-Type': 'application/json'}

try:
    resp = httpx.post(url, json=payload, headers=headers, timeout=60)
    data = resp.json()
    print('=== Full Response ===')
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()
    print('=== Message Keys ===')
    if data.get('choices'):
        msg = data['choices'][0].get('message', {})
        print('Keys:', list(msg.keys()))
        print('Has reasoning_content:', 'reasoning_content' in msg)
        print('Has reasoning:', 'reasoning' in msg)
        if 'reasoning_content' in msg:
            rc = msg['reasoning_content']
            print('reasoning_content:', (rc[:500] if rc else 'None'))
        if 'reasoning' in msg:
            print('reasoning:', str(msg['reasoning'])[:500])
        print('content:', msg.get('content', '')[:500])
    elif data.get('error'):
        print('Error:', data['error'])
except Exception as e:
    print(f'Error: {e}')
