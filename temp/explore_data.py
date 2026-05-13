import psycopg2
import json
import pickle

def explore_data(thread_id):
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="deerflow",
        user="postgres",
        password="yuhan1014"
    )
    cur = conn.cursor()
    
    # 查看 checkpoint_writes 的样本数据
    cur.execute("""
        SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob
        FROM checkpoint_writes
        WHERE thread_id = %s
        ORDER BY checkpoint_id, idx
        LIMIT 30;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"=== checkpoint_writes 样本数据 (前30条) ===")
    for row in rows:
        print(f"\n  checkpoint_id: {row[2][:12]}...")
        print(f"  task_id: {row[3]}")
        print(f"  idx: {row[4]}")
        print(f"  channel: {row[5]}")
        print(f"  type: {row[6]}")
        blob = row[7]
        if blob:
            # 尝试解析 blob
            try:
                # Try pickle first
                data = pickle.loads(blob)
                print(f"  blob (pickle): {str(data)[:300]}")
            except:
                try:
                    # Try JSON
                    data = json.loads(blob.decode('utf-8'))
                    print(f"  blob (json): {json.dumps(data, ensure_ascii=False)[:300]}")
                except:
                    try:
                        print(f"  blob (utf-8): {blob.decode('utf-8')[:300]}")
                    except:
                        print(f"  blob (raw bytes, len={len(blob)}): {blob[:100]}")
    
    # 查看 checkpoint_blobs 样本
    cur.execute("""
        SELECT thread_id, checkpoint_ns, channel, version, type, blob
        FROM checkpoint_blobs
        WHERE thread_id = %s
        ORDER BY version
        LIMIT 20;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"\n\n=== checkpoint_blobs 样本数据 (前20条) ===")
    for row in rows:
        print(f"\n  channel: {row[2]}")
        print(f"  version: {row[3]}")
        print(f"  type: {row[4]}")
        blob = row[5]
        if blob:
            try:
                data = pickle.loads(blob)
                print(f"  blob (pickle): {str(data)[:500]}")
            except:
                try:
                    data = json.loads(blob.decode('utf-8'))
                    print(f"  blob (json): {json.dumps(data, ensure_ascii=False)[:500]}")
                except:
                    try:
                        text = blob.decode('utf-8')
                        print(f"  blob (utf-8): {text[:500]}")
                    except:
                        print(f"  blob (raw bytes, len={len(blob)}): {blob[:200]}")
    
    # 查看 checkpoint 的详细结构（使用一个有消息的 checkpoint）
    cur.execute("""
        SELECT checkpoint_id, checkpoint, metadata
        FROM checkpoints 
        WHERE thread_id = %s
        ORDER BY checkpoint_id DESC
        LIMIT 1;
    """, (thread_id,))
    
    row = cur.fetchone()
    if row:
        cp = row[1]
        print(f"\n\n=== 最新 checkpoint 详情 ===")
        print(f"  checkpoint_id: {row[0]}")
        print(f"  top-level keys: {list(cp.keys())}")
        
        cv = cp.get("channel_values", {})
        print(f"  channel_values keys: {list(cv.keys())}")
        
        for key, val in cv.items():
            if isinstance(val, dict):
                print(f"  {key} (dict keys): {list(val.keys())[:10]}")
            elif isinstance(val, list):
                print(f"  {key} (list len={len(val)})")
                if val:
                    print(f"    first item type: {type(val[0])}")
                    if isinstance(val[0], dict):
                        print(f"    first item keys: {list(val[0].keys())}")
            elif isinstance(val, str):
                print(f"  {key} (str): {val[:200]}")
            else:
                print(f"  {key}: {type(val).__name__} = {str(val)[:200]}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    explore_data(thread_id)
