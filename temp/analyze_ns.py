import psycopg2
import json

def analyze_namespaces():
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="deerflow",
        user="postgres",
        password="yuhan1014"
    )
    cur = conn.cursor()
    
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    
    # 检查不同的 checkpoint_ns
    cur.execute("""
        SELECT checkpoint_ns, COUNT(*) as cnt
        FROM checkpoints
        WHERE thread_id = %s
        GROUP BY checkpoint_ns
        ORDER BY cnt DESC;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"=== checkpoint_ns 分布 ===")
    for row in rows:
        ns = row[0] if row[0] else "(root)"
        print(f"  {ns}: {row[1]} checkpoints")
    
    # 检查 checkpoint_writes 的 channel 分布
    cur.execute("""
        SELECT channel, COUNT(*) as cnt
        FROM checkpoint_writes
        WHERE thread_id = %s
        GROUP BY channel
        ORDER BY cnt DESC
        LIMIT 30;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"\n=== checkpoint_writes channel 分布 (top 30) ===")
    for row in rows:
        print(f"  {row[0]}: {row[1]}")
    
    # 检查 checkpoint_blobs 的 channel 分布
    cur.execute("""
        SELECT channel, COUNT(*) as cnt
        FROM checkpoint_blobs
        WHERE thread_id = %s
        GROUP BY channel
        ORDER BY cnt DESC
        LIMIT 30;
    """, (thread_id,))
    
    rows = cur.fetchall()
    print(f"\n=== checkpoint_blobs channel 分布 (top 30) ===")
    for row in rows:
        print(f"  {row[0]}: {row[1]}")
    
    # 检查 __start__ channel 的 blob 数量（每个代表一次用户输入/子agent启动）
    cur.execute("""
        SELECT COUNT(*)
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = '__start__';
    """, (thread_id,))
    
    count = cur.fetchone()[0]
    print(f"\n=== __start__ blobs: {count} (代表子agent/输入启动次数) ===")
    
    # 检查 messages channel 的 blob 数量
    cur.execute("""
        SELECT COUNT(*)
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages';
    """, (thread_id,))
    
    count = cur.fetchone()[0]
    print(f"=== messages blobs: {count} ===")
    
    # 检查 store 表中该 thread 的信息
    cur.execute("""
        SELECT *
        FROM store
        LIMIT 5;
    """)
    
    # 先看 store 表结构
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'store'
        ORDER BY ordinal_position;
    """)
    print(f"\n=== store 表结构 ===")
    for col in cur.fetchall():
        print(f"  {col[0]}: {col[1]}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    analyze_namespaces()
