import psycopg2
import json
from datetime import datetime

def query_thread(thread_id):
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="deerflow",
        user="postgres",
        password="yuhan1014"
    )
    cur = conn.cursor()
    
    # 查询该 thread 的 checkpoints
    cur.execute("""
        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
        FROM checkpoints 
        WHERE thread_id = %s
        ORDER BY checkpoint_id;
    """, (thread_id,))
    
    checkpoints = cur.fetchall()
    print(f"=== thread {thread_id} 的 checkpoints ({len(checkpoints)} 条) ===")
    
    for i, cp in enumerate(checkpoints):
        checkpoint_data = cp[5]  # checkpoint jsonb
        metadata = cp[6]  # metadata jsonb
        
        # 获取 channel_values 中的消息
        channel_values = checkpoint_data.get("channel_values", {}) if checkpoint_data else {}
        messages = channel_values.get("messages", [])
        
        print(f"\n--- Checkpoint {i+1}/{len(checkpoints)} ---")
        print(f"  checkpoint_id: {cp[2]}")
        print(f"  parent: {cp[3]}")
        print(f"  type: {cp[4]}")
        
        if metadata:
            source = metadata.get("source", "unknown")
            step = metadata.get("step", "N/A")
            print(f"  source: {source}, step: {step}")
        
        if messages:
            print(f"  messages count: {len(messages)}")
            # 打印最后几条消息的摘要
            for msg in messages[-3:]:
                if isinstance(msg, dict):
                    msg_type = msg.get("type", "unknown")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # tool_use messages
                        content_str = str(content)[:100]
                    else:
                        content_str = str(content)[:100]
                    print(f"    [{msg_type}] {content_str}")
                else:
                    print(f"    {str(msg)[:100]}")
    
    # 检查 checkpoint_writes 表
    cur.execute("""
        SELECT COUNT(*) 
        FROM checkpoint_writes 
        WHERE thread_id = %s;
    """, (thread_id,))
    write_count = cur.fetchone()[0]
    print(f"\n=== checkpoint_writes: {write_count} 条 ===")
    
    # 检查 store 表
    cur.execute("""
        SELECT namespace, key, value
        FROM store 
        WHERE key = %s OR key LIKE %s;
    """, (thread_id, f"%{thread_id}%"))
    store_items = cur.fetchall()
    print(f"\n=== store 中的记录: {len(store_items)} 条 ===")
    for item in store_items:
        print(f"  namespace: {item[0]}, key: {item[1]}")
        if item[2]:
            val = item[2]
            if isinstance(val, dict):
                print(f"  value keys: {list(val.keys())}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    query_thread(thread_id)
