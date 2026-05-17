"""
测试 LM Studio Qwen3.6 模型的 reasoning_content 返回格式
用法：先在 LM Studio 中加载模型，然后运行此脚本
"""
import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://192.168.31.187:1234/v1"
MODEL = "qwen-3-6-local"

def test_non_streaming():
    print("=" * 60)
    print("测试1: 非流式请求 - 检查 reasoning_content 字段")
    print("=" * 60)
    
    url = f"{BASE_URL}/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "1+1等于几？请思考一下。"}],
        "max_tokens": 1000,
        "stream": False
    }
    
    try:
        resp = httpx.post(url, json=payload, timeout=120)
        data = resp.json()
        
        if data.get("error"):
            print(f"  ❌ 错误: {data['error']['message']}")
            return False
        
        if not data.get("choices"):
            print("  ❌ 无 choices 返回")
            return False
        
        msg = data["choices"][0].get("message", {})
        print(f"  Message keys: {list(msg.keys())}")
        print(f"  Has reasoning_content: {'reasoning_content' in msg}")
        print(f"  Has reasoning: {'reasoning' in msg}")
        
        if "reasoning_content" in msg and msg["reasoning_content"]:
            print(f"  ✅ reasoning_content 存在!")
            print(f"  reasoning_content (前200字): {msg['reasoning_content'][:200]}")
        elif "reasoning" in msg and msg["reasoning"]:
            print(f"  ✅ reasoning 存在!")
            print(f"  reasoning (前200字): {str(msg['reasoning'])[:200]}")
        else:
            content = msg.get("content", "")
            if "<tool_call>" in content:
                print(f"  ⚠️ reasoning_content 不存在，但 content 中包含 <tool_call> 标签")
                print(f"  content (前300字): {content[:300]}")
            else:
                print(f"  ❌ 没有找到任何思考内容!")
                print(f"  content (前200字): {content[:200]}")
        
        print(f"  content (前200字): {msg.get('content', '')[:200]}")
        return True
        
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return False


def test_streaming():
    print()
    print("=" * 60)
    print("测试2: 流式请求 - 检查 delta 中的 reasoning_content")
    print("=" * 60)
    
    url = f"{BASE_URL}/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "1+1等于几？请思考一下。"}],
        "max_tokens": 1000,
        "stream": True
    }
    
    try:
        reasoning_chunks = []
        content_chunks = []
        delta_keys = set()
        
        with httpx.stream("POST", url, json=payload, timeout=120) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                
                choices = data.get("choices", [])
                if not choices:
                    continue
                
                delta = choices[0].get("delta", {})
                delta_keys.update(delta.keys())
                
                if "reasoning_content" in delta and delta["reasoning_content"]:
                    reasoning_chunks.append(delta["reasoning_content"])
                if "reasoning" in delta and delta["reasoning"]:
                    reasoning_chunks.append(str(delta["reasoning"]))
                if "content" in delta and delta["content"]:
                    content_chunks.append(delta["content"])
        
        print(f"  Delta keys seen: {delta_keys}")
        print(f"  Has reasoning_content in delta: {'reasoning_content' in delta_keys}")
        print(f"  Has reasoning in delta: {'reasoning' in delta_keys}")
        
        if reasoning_chunks:
            full_reasoning = "".join(reasoning_chunks)
            print(f"  ✅ 捕获到思考内容! (长度: {len(full_reasoning)})")
            print(f"  思考内容 (前200字): {full_reasoning[:200]}")
        else:
            full_content = "".join(content_chunks)
            if "<tool_call>" in full_content:
                print(f"  ⚠️ delta 中没有 reasoning_content，但 content 包含 <tool_call> 标签")
            else:
                print(f"  ❌ 流式响应中没有找到思考内容")
        
        if content_chunks:
            full_content = "".join(content_chunks)
            print(f"  正式内容 (前200字): {full_content[:200]}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return False


def test_with_adapter():
    print()
    print("=" * 60)
    print("测试3: 使用 GenericPatchedChatOpenAI 适配器")
    print("=" * 60)
    
    try:
        from deerflow.models.patched_generic_openai import GenericPatchedChatOpenAI
        
        model = GenericPatchedChatOpenAI(
            model=MODEL,
            api_key="sk-lm-xDm8HLPW:f0xVpYVgwbHGnQTqfsSA",
            base_url=BASE_URL,
            max_tokens=1000,
            temperature=1,
        )
        
        from langchain_core.messages import HumanMessage
        result = model.invoke([HumanMessage(content="1+1等于几？请思考一下。")])
        
        print(f"  AIMessage type: {type(result).__name__}")
        print(f"  additional_kwargs keys: {list(result.additional_kwargs.keys())}")
        print(f"  Has reasoning_content: {'reasoning_content' in result.additional_kwargs}")
        print(f"  Has reasoning: {'reasoning' in result.additional_kwargs}")
        
        if "reasoning_content" in result.additional_kwargs:
            rc = result.additional_kwargs["reasoning_content"]
            print(f"  ✅ reasoning_content 被适配器捕获!")
            print(f"  reasoning_content (前200字): {str(rc)[:200]}")
        else:
            print(f"  ❌ 适配器未捕获到 reasoning_content")
        
        content = result.content if isinstance(result.content, str) else str(result.content)
        print(f"  content (前200字): {content[:200]}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ 适配器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("LM Studio Qwen3.6 思考内容测试")
    print(f"API: {BASE_URL}")
    print(f"Model: {MODEL}")
    print()
    
    test_non_streaming()
    test_streaming()
    test_with_adapter()
    
    print()
    print("=" * 60)
    print("测试完成！")
    print("如果测试1/2显示有 reasoning_content 但测试3没有捕获，说明适配器有问题")
    print("如果测试1/2就没有 reasoning_content，说明 LM Studio 没有返回思考内容")
    print("=" * 60)
