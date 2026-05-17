import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'http://192.168.31.187:1234/v1/chat/completions'
payload = {
    'model': 'qwen-3-6-local',
    'messages': [{'role': 'user', 'content': '1+1=?'}],
    'max_tokens': 500,
    'stream': False
}
headers = {'Content-Type': 'application/json'}

try:
    resp = httpx.post(url, json=payload, headers=headers, timeout=30)
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
            print('reasoning_content:', (rc[:200] if rc else 'None'))
        if 'reasoning' in msg:
            print('reasoning:', str(msg['reasoning'])[:200])
        print('content:', msg.get('content', '')[:200])
except Exception as e:
    print(f'Error: {e}')
