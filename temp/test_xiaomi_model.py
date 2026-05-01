# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests

API_KEY = "tp-ctk0l4oybbr3xhzesr3fjz61488ehzz90tqlzevmnagy0qga"
BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL = "mimo-v2.5-pro"

def chat_with_xiaomi(prompt: str, max_tokens: int = 2048, temperature: float = 0.7):
    url = f"{BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    
    result = response.json()
    return result["choices"][0]["message"]["content"]

def chat_with_history(messages: list, max_tokens: int = 2048, temperature: float = 0.7):
    url = f"{BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    
    result = response.json()
    return result["choices"][0]["message"]["content"]

if __name__ == "__main__":
    print("小米 MiMo-V2.5-Pro 模型测试")
    print("=" * 50)
    
    test_prompt = "你好，请简单介绍一下你自己。"
    print(f"\n用户: {test_prompt}")
    
    try:
        response = chat_with_xiaomi(test_prompt)
        print(f"\nAI: {response}")
    except requests.exceptions.HTTPError as e:
        print(f"\nHTTP 错误: {e}")
        print(f"响应内容: {e.response.text}")
    except Exception as e:
        print(f"\n调用失败: {e}")
