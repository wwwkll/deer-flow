import psycopg2
import json
import msgpack

def extract_conversation(thread_id):
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="deerflow",
        user="postgres",
        password="yuhan1014"
    )
    cur = conn.cursor()
    
    # 获取 checkpoint_blobs 中的消息数据
    cur.execute("""
        SELECT channel, version, type, blob
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages'
        ORDER BY version
        LIMIT 5;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"=== checkpoint_blobs 中 messages channel 样本 ({len(rows)} 条) ===")
    for row in rows:
        print(f"\n  channel: {row[0]}")
        print(f"  version: {row[1]}")
        print(f"  type: {row[2]}")
        blob = row[3]
        if blob:
            try:
                data = msgpack.unpackb(blob, raw=False)
                if isinstance(data, list):
                    print(f"  msgpack (list len={len(data)}):")
                    for item in data[:3]:
                        if isinstance(item, dict):
                            msg_type = item.get("type", "?")
                            content = item.get("content", "")
                            if isinstance(content, str):
                                print(f"    [{msg_type}] {content[:200]}")
                            elif isinstance(content, list):
                                texts = []
                                for c in content:
                                    if isinstance(c, dict):
                                        if c.get("type") == "text":
                                            texts.append(c.get("text", "")[:100])
                                        elif c.get("type") == "tool_use":
                                            texts.append(f"[tool:{c.get('name','')}]")
                                print(f"    [{msg_type}] {' '.join(texts)[:200]}")
                        else:
                            print(f"    {str(item)[:200]}")
                elif isinstance(data, dict):
                    print(f"  msgpack (dict keys): {list(data.keys())[:10]}")
                else:
                    print(f"  msgpack: {str(data)[:300]}")
            except Exception as e:
                print(f"  msgpack error: {e}")
                try:
                    text = blob.decode('utf-8')
                    print(f"  utf-8: {text[:300]}")
                except:
                    print(f"  raw bytes len={len(blob)}")
    
    # 获取所有 messages channel 的 blobs，统计总数
    cur.execute("""
        SELECT COUNT(*), MIN(version), MAX(version)
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages';
    """, (thread_id,))
    
    row = cur.fetchone()
    print(f"\n=== messages channel blobs 总计: {row[0]} 条 ===")
    print(f"  version range: {row[1]} ~ {row[2]}")
    
    # 获取最新的 messages blob（包含完整对话）
    cur.execute("""
        SELECT channel, version, type, blob
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages'
        ORDER BY version DESC
        LIMIT 1;
    """, (thread_id,))
    
    row = cur.fetchone()
    if row:
        blob = row[3]
        try:
            data = msgpack.unpackb(blob, raw=False)
            if isinstance(data, list):
                print(f"\n=== 最新 messages blob: {len(data)} 条消息 ===")
                
                # 统计消息类型
                type_counts = {}
                for msg in data:
                    if isinstance(msg, dict):
                        t = msg.get("type", "unknown")
                        type_counts[t] = type_counts.get(t, 0) + 1
                print(f"  消息类型统计: {type_counts}")
                
                # 打印所有用户消息
                print(f"\n--- 用户消息 ---")
                for i, msg in enumerate(data):
                    if isinstance(msg, dict) and msg.get("type") == "human":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            print(f"\n[用户 {i}] {content[:500]}")
                        elif isinstance(content, list):
                            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                            print(f"\n[用户 {i}] {' '.join(texts)[:500]}")
                
                # 打印AI回复（仅含 tool_use 的）
                print(f"\n--- AI回复摘要 (前20条) ---")
                ai_count = 0
                for i, msg in enumerate(data):
                    if isinstance(msg, dict) and msg.get("type") == "ai":
                        ai_count += 1
                        if ai_count > 20:
                            break
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])
                        if isinstance(content, str) and content:
                            print(f"\n[AI {i}] text: {content[:300]}")
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict):
                                    if c.get("type") == "text" and c.get("text"):
                                        print(f"\n[AI {i}] text: {c['text'][:300]}")
                                    elif c.get("type") == "tool_use":
                                        print(f"\n[AI {i}] tool_use: {c.get('name', '?')} - args: {json.dumps(c.get('input', {}), ensure_ascii=False)[:200]}")
                        if tool_calls:
                            for tc in tool_calls:
                                print(f"\n[AI {i}] tool_call: {tc.get('name', '?')}")
        except Exception as e:
            print(f"  msgpack error: {e}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    extract_conversation(thread_id)
