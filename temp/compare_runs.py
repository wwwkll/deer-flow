import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="deerflow",
    user="postgres",
    password="yuhan1014"
)
cur = conn.cursor()

thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"

# 获取最新的 run (019e26e0) 和之前的大 run (019e2200) 的 checkpoint_ns 对比
runs = {
    "新run (代码修改后)": "019e26e0-c107-7a92-98ad-8b02466225c4",
    "旧run (代码修改前)": "019e2200-6096-7db3-92d3-974e6476fda2",
}

for label, run_id in runs.items():
    cur.execute("""
        SELECT checkpoint_ns, COUNT(*) as cnt
        FROM checkpoints
        WHERE thread_id = %s AND metadata->>'run_id' = %s
        GROUP BY checkpoint_ns
        ORDER BY cnt DESC;
    """, (thread_id, run_id))
    
    rows = cur.fetchall()
    print(f"\n{'='*60}")
    print(f"=== {label} ===")
    print(f"总 checkpoint: {sum(r[1] for r in rows)}")
    print(f"不同 namespace 数: {len(rows)}")
    
    # 分类统计
    root_cnt = 0
    update_world_cnt = 0
    call_planner_cnt = 0
    organize_cnt = 0
    write_chapter_cnt = 0
    audit_cnt = 0
    revise_cnt = 0
    other_cnt = 0
    
    for ns, cnt in rows:
        if not ns:
            root_cnt += cnt
        elif 'update_world_file' in ns:
            update_world_cnt += cnt
        elif 'call_planner' in ns:
            call_planner_cnt += cnt
        elif 'organize_' in ns:
            organize_cnt += cnt
        elif 'write_chapter' in ns:
            write_chapter_cnt += cnt
        elif 'audit' in ns:
            audit_cnt += cnt
        elif 'revise' in ns:
            revise_cnt += cnt
        else:
            other_cnt += cnt
    
    print(f"\n  root namespace:       {root_cnt}")
    print(f"  update_world_file:    {update_world_cnt}")
    print(f"  call_planner:         {call_planner_cnt}")
    print(f"  organize_*:           {organize_cnt}")
    print(f"  write_chapter:        {write_chapter_cnt}")
    print(f"  audit:                {audit_cnt}")
    print(f"  revise:               {revise_cnt}")
    print(f"  other:                {other_cnt}")
    
    # 打印前 10 个 namespace
    print(f"\n  Top namespaces:")
    for ns, cnt in rows[:10]:
        ns_display = ns[:70] if ns else "(root)"
        print(f"    {ns_display}: {cnt}")

cur.close()
conn.close()
