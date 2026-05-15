import psycopg2
import json
import msgpack

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="deerflow",
    user="postgres",
    password="yuhan1014"
)
cur = conn.cursor()

thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"

# 1. 获取最新的 checkpoints 的 run_id
cur.execute("""
    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
    FROM checkpoints 
    WHERE thread_id = %s
    ORDER BY checkpoint_id DESC
    LIMIT 5;
""", (thread_id,))

rows = cur.fetchall()
print("=== 最新 5 个 checkpoint ===")
for row in rows:
    meta = row[6]
    cp = row[5]
    run_id = meta.get("run_id", "?") if meta else "?"
    step = meta.get("step", -1) if meta else -1
    source = meta.get("source", "?") if meta else "?"
    agent = meta.get("agent_name", "?") if meta else "?"
    print(f"  run: {run_id[:16]}... | step: {step} | source: {source} | agent: {agent}")
    
    cv = cp.get("channel_values", {})
    messages = cv.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, 'type'):
            msg_type = last_msg.type
            content = last_msg.content if hasattr(last_msg, 'content') else ""
            if isinstance(content, str):
                print(f"    last_msg: [{msg_type}] {content[:200]}")
            elif isinstance(content, list):
                texts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get('type') == 'text':
                            texts.append(c.get('text', '')[:100])
                        elif c.get('type') == 'tool_use':
                            texts.append(f"[tool:{c.get('name','')}]")
                        elif c.get('type') == 'tool_result':
                            texts.append(f"[tool_result]")
                print(f"    last_msg: [{msg_type}] {' '.join(texts)[:200]}")
            else:
                print(f"    last_msg: [{msg_type}] {str(content)[:200]}")
        else:
            print(f"    last_msg: {str(last_msg)[:200]}")

# 2. 统计总 checkpoint 数量
cur.execute("""
    SELECT COUNT(*) FROM checkpoints WHERE thread_id = %s;
""", (thread_id,))
total = cur.fetchone()[0]
print(f"\n=== 总 checkpoint 数: {total} ===")

# 3. 对比 checkpoint_writes 表结构
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'checkpoint_writes'
    ORDER BY ordinal_position;
""")
print("\n=== checkpoint_writes 表结构 ===")
cols = cur.fetchall()
for col in cols:
    print(f"  {col[0]}: {col[1]}")

# 4. 获取 checkpoint_writes 中 workflow 相关的记录
cur.execute("""
    SELECT *
    FROM checkpoint_writes
    WHERE thread_id = %s
    ORDER BY checkpoint_id DESC
    LIMIT 5;
""", (thread_id,))

rows = cur.fetchall()
if rows:
    print(f"\n=== checkpoint_writes 最新 5 条 ===")
    for row in rows:
        val = row[7]  # blob column
        print(f"  cp_id: {row[2][:12]}... | ns: {row[1]} | idx: {row[4]} | channel: {row[5]} | type: {row[6]}")
        if val:
            try:
                data = msgpack.unpackb(val, raw=False)
                print(f"  value: {str(data)[:300]}")
            except:
                print(f"  value (raw): {str(val)[:200]}")

# 5. 检查不同 checkpoint_ns 的分布
cur.execute("""
    SELECT checkpoint_ns, COUNT(*) as cnt
    FROM checkpoints
    WHERE thread_id = %s
    GROUP BY checkpoint_ns
    ORDER BY cnt DESC;
""", (thread_id,))

rows = cur.fetchall()
print(f"\n=== checkpoint_ns 分布 ===")
for row in rows:
    ns = row[0] if row[0] else "(root)"
    print(f"  {ns[:60]}: {row[1]}")

# 6. 获取所有 run_id 的统计
cur.execute("""
    SELECT metadata->>'run_id' as run_id, COUNT(*) as cnt, 
           MIN(COALESCE(metadata->>'step', '0')::int) as min_step, 
           MAX(COALESCE(metadata->>'step', '0')::int) as max_step,
           COALESCE(MAX(metadata->>'agent_name'), '?') as agent
    FROM checkpoints
    WHERE thread_id = %s
    GROUP BY metadata->>'run_id'
    ORDER BY MAX(checkpoint_id) DESC
    LIMIT 15;
""", (thread_id,))

rows = cur.fetchall()
print(f"\n=== 最新 15 个 Run ===")
for row in rows:
    print(f"  run: {row[0][:16]}... | cps: {row[1]} | steps: {row[2]}~{row[3]} | agent: {row[4]}")

cur.close()
conn.close()
