import asyncio
import time
import httpx

API_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
API_KEY = "tp-ctk0l4oybbr3xhzesr3fjz61488ehzz90tqlzevmnagy0qga"
MODEL = "mimo-v2-omni"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

PAYLOAD = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
    "max_tokens": 10,
    "temperature": 0,
}


async def single_request(client: httpx.AsyncClient, index: int):
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{API_BASE}/chat/completions",
            headers=HEADERS,
            json=PAYLOAD,
            timeout=30.0,
        )
        elapsed = time.perf_counter() - start
        status = resp.status_code
        body = resp.json()
        error = body.get("error", {}).get("message", "")
        content = ""
        if body.get("choices"):
            content = body["choices"][0].get("message", {}).get("content", "")[:50]
        return {
            "index": index,
            "status": status,
            "elapsed": round(elapsed, 2),
            "content": content,
            "error": error,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "index": index,
            "status": "ERROR",
            "elapsed": round(elapsed, 2),
            "content": "",
            "error": str(e),
        }


async def test_concurrency(n: int):
    print(f"\n{'='*60}")
    print(f"  并发测试: 同时发送 {n} 个请求到 mimo-v2-omni")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient() as client:
        start = time.perf_counter()
        tasks = [single_request(client, i) for i in range(n)]
        results = await asyncio.gather(*tasks)
        total_elapsed = time.perf_counter() - start

    success = [r for r in results if r["status"] == 200]
    failed = [r for r in results if r["status"] != 200]

    print(f"总耗时: {round(total_elapsed, 2)}s")
    print(f"成功: {len(success)} | 失败: {len(failed)}\n")

    print(f"{'#':>3} | {'Status':>6} | {'耗时(s)':>8} | 响应/错误")
    print(f"{'-'*3}-+-{'-'*6}-+-{'-'*8}-+-{'-'*40}")
    for r in results:
        detail = r["error"] if r["error"] else r["content"]
        print(f"{r['index']:>3} | {str(r['status']):>6} | {r['elapsed']:>8} | {detail}")

    if failed:
        print(f"\n--- 错误详情 ---")
        for r in failed:
            print(f"  请求#{r['index']}: {r['error']}")

    return results


async def main():
    for n in [1, 2, 3, 5]:
        await test_concurrency(n)
        print()
        if n < 5:
            print("等待 3 秒后继续下一组测试...\n")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
