"""
Recover config.yaml by reconstructing truncated UTF-8 characters.
Each 2-byte prefix + '?' is mapped to the correct 3-byte UTF-8 char based on context analysis.
"""

backup = r"c:\xiangmu\deer-flow\config.yaml.bak"
output = r"c:\xiangmu\deer-flow\config.yaml"

with open(backup, "rb") as f:
    raw = f.read()

# Mapping of (prefix_bytes) -> correct_3rd_byte, determined by context analysis
# Format: prefix -> expected_3rd_byte
CHAR_MAP = {
    # 。 U+3002 Chinese period (most common, 80 occurrences)
    b'\xe3\x80': b'\x82',
    
    # ： U+FF1A fullwidth colon (19 of 19 \xef\xbc are this)
    b'\xef\xbc': b'\x9a',
    
    # 态 U+6001 (态->状态, 16 of 16 \xe6\x80 are this)
    b'\xe6\x80': b'\x81',
    
    # 老 U+8001 or 者 U+8005 - context shows it's 者 (in "读者" etc)
    b'\xe8\x80': b'\x85',
    
    # 纲 U+7EB2 (卷纲, 7 of 7 \xe7\xba are this)
    b'\xe7\xba': b'\xa1',
    
    # 划 U+5212 (规划, 7 of 7 \xe5\x88 are this)
    b'\xe5\x88': b'\x92',
    
    # 们 U+4EEC or 什 U+4EC0 or 似 U+4F3C - context: "从什么" "他们"
    b'\xe4\xbb': b'\x80',  # 什么
    
    # 值 U+503C (数值, 7 of 7 \xe5\x80 are this)
    b'\xe5\x80': b'\xbc',
    
    # 况 U+60C1 (剧情状况/情况, 5 of 5 \xe6\x83 are this)
    b'\xe6\x83': b'\x81',
    
    # 定 U+5B9A (设定, 4 of 4 \xe5\xae are this)
    b'\xe5\xae': b'\x9a',
    
    # 笔 U+7B14 (伏笔, 4 of 4 \xe7\xac are this)
    b'\xe7\xac': b'\x94',
    
    # 和 U+548C (和, 3 of 3 \xe5\x92 are this)
    b'\xe5\x92': b'\x8c',
    
    # 点 U+70B9 (转折点/关键点, 3 of 3 \xe7\x82 are this)
    b'\xe7\x82': b'\xb9',
    
    # 说 U+8BF4 (说明/小说, 3 of 3 \xe8\xaf are this)
    b'\xe8\xaf': b'\xb4',
    
    # 不 U+4E0D (不可/不要, 3 of 3 \xe4\xb8 are this)
    b'\xe4\xb8': b'\x8d',
    
    # 取 U+53D6 or 反 U+53CD - context: "提取" "参考"
    b'\xe5\x8f': b'\x96',
    
    # 图 U+56FE (路线图/伏笔图, 2 of 2 \xe5\x9b are this)
    b'\xe5\x9b': b'\xbe',
    
    # 池 U+6C60 (伏笔池, 2 of 2 \xe6\xb1 are this)
    b'\xe6\xb1': b'\xa0',
    
    # 护 U+62A4 (维护, 2 of 2 \xe6\x8a are this)
    b'\xe6\x8a': b'\xa4',
    
    # 致 U+81F4 (一致, 2 of 2 \xe8\x87 are this)
    b'\xe8\x87': b'\xb4',
    
    # 字 U+5B50 (钩子/字数, 2 of 2 \xe5\xad are this)
    b'\xe5\xad': b'\x97',
    
    # 理 U+7406 (管理器/整理, 2 of 2 \xe7\x90 are this)
    b'\xe7\x90': b'\x86',
    
    # 议 U+8BAE (建议, 2 of 2 \xe8\xae are this)
    b'\xe8\xae': b'\xae',
    
    # 用 U+5E94 (应用, 2 of 2 \xe5\xba are this)
    b'\xe5\xba': b'\x94',
    
    # 息 U+606F (信息, 2 of 2 \xe6\x81 are this)
    b'\xe6\x81': b'\xaf',
    
    # 力 U+80FD (能力/技能, 2 of 2 \xe8\x83 are this)
    b'\xe8\x83': b'\xbd',
    
    # 节 U+8282 (章节/节奏, 2 of 2 \xe8\x8a are this)
    b'\xe8\x8a': b'\x82',
    
    # 篇 U+7BC7 (开篇/短篇, 2 of 2 \xe7\xaf are this)
    b'\xe7\xaf': b'\x87',
    
    # 章 U+7AE0 (章节, 2 of 2 \xe7\xab are this)
    b'\xe7\xab': b'\xa0',
    
    # 题 U+9898 (问题/主题, 2 of 2 \xe9\xa2 are this)
    b'\xe9\xa2': b'\x98',
    
    # 向 U+2192 (arrow, 2 of 2 \xe2\x86 are this)
    b'\xe2\x86': b'\x92',
    
    # 过 U+8FC7 (超过, 2 of 2 \xe8\xbf are this)
    b'\xe8\xbf': b'\x87',
    
    # 建 U+5EFA (构建, 1 occurrence)
    b'\xe5\xbb': b'\xba',
    
    # 力 U+529B (吸引力, 1 occurrence)
    b'\xe5\x8a': b'\x9b',
    
    # 盾 U+76FE (矛盾, 1 occurrence)
    b'\xe7\x9b': b'\x9e',
    
    # 行 U+884C (执行, 1 occurrence)
    b'\xe8\xa1': b'\x8c',
    
    # 待 U+5F85 (期待/期待感, 1 occurrence)
    b'\xe5\xbe': b'\x85',
    
    # 引 U+5F15 (钩引/牵引, 1 occurrence)
    b'\xe5\xbc': b'\x95',
    
    # 更 U+66F4 (交替/更替, 1 occurrence)
    b'\xe6\x9b': b'\xb4',
    
    # 必 U+5FC5 (悬念必, 1 occurrence)
    b'\xe5\xbf': b'\x85',
    
    # 每 U+6BCF (每章, 1 occurrence)
    b'\xe6\xaf': b'\x8f',
    
    # 置 U+7F6E (设置/布置, 1 occurrence)
    b'\xe7\xbd': b'\xae',
    
    # 保 U+4FDD (确保, 1 occurrence)
    b'\xe4\xbf': b'\x9d',
    
    # 貌 U+8C8C (外貌, 1 occurrence)
    b'\xe8\xb2': b'\x8c',
    
    # 标 U+6807 (目标, 1 occurrence)
    b'\xe6\xa0': b'\x87',
    
    # 系 U+7CFB (关系, 1 occurrence)
    b'\xe7\xb3': b'\xbb',
    
    # 奏 U+594F (节奏, 1 occurrence)
    b'\xe5\xa5': b'\x8f',
    
    # 在 U+5728 (存在/所在, 1 occurrence)
    b'\xe5\x9c': b'\xa8',
    
    # 当 U+5F53 (当前, 1 occurrence)
    b'\xe5\xbd': b'\x93',
    
    # 溯 U+6EAF (追溯, 1 occurrence)
    b'\xe6\xba': b'\xaf',
    
    # 续 U+7EED (连续/后续, 1 occurrence)
    b'\xe7\xbb': b'\xad',
    
    # 突 U+7A81 (冲突, 1 occurrence)
    b'\xe7\xaa': b'\x81',
    
    # 构 U+6784 (结构, 1 occurrence)
    b'\xe6\x9e': b'\x84',
    
    # 免 U+514D (避免, 1 occurrence)
    b'\xe5\x85': b'\x8d',
    
    # 等 U+7B49 (等待, 1 occurrence)
    b'\xe7\xad': b'\x89',
    
    # 照 U+7167 (参照, 1 occurrence)
    b'\xe7\x85': b'\xa7',
    
    # 测 U+6D4B (检测, 1 occurrence)
    b'\xe6\xb5': b'\x8b',
    
    # 离 U+79BB (偏离, 1 occurrence)
    b'\xe7\xa6': b'\xbb',
    
    # 景 U+666F (场景, 1 occurrence)
    b'\xe6\x99': b'\xaf',
    
    # 项 U+9879 (事项, 1 occurrence)
    b'\xe9\xa1': b'\xb9',
    
    # 文 U+6587 (正文, 1 occurrence)
    b'\xe6\x96': b'\x87',
    
    # 么 U+4E48 (什么, 1 occurrence)
    b'\xe4\xb9': b'\x88',
    
    # 据 U+6570 (数据, 1 occurrence)
    b'\xe6\x95': b'\xae',
    
    # 段 U+6BB5 (字段/段落, 1 occurrence)
    b'\xe6\xae': b'\xb5',
    
    # 决 U+51B3 (解决, 1 occurrence)
    b'\xe5\x86': b'\xb3',
    
    # 确 U+786E (准确, 1 occurrence)
    b'\xe7\xa1': b'\xae',
    
    # 档 U+6863 (归档, 1 occurrence)
    b'\xe6\xa1': b'\xa3',
}

# Now reconstruct the file
result = bytearray()
i = 0
replaced = 0

while i < len(raw):
    # Check if we're at a 2-byte UTF-8 prefix followed by '?'
    if i + 2 < len(raw) and raw[i+2] == 0x3F:
        prefix = raw[i:i+2]
        if prefix in CHAR_MAP:
            third_byte = CHAR_MAP[prefix]
            result.append(raw[i])
            result.append(raw[i+1])
            result.append(third_byte[0])
            i += 3
            replaced += 1
            continue
    
    result.append(raw[i])
    i += 1

fixed = bytes(result)

# Verify UTF-8 validity
try:
    fixed.decode("utf-8")
    print(f"SUCCESS: Valid UTF-8, replaced {replaced} characters")
except UnicodeDecodeError as e:
    print(f"STILL HAS ERRORS: {e}")
    # Show remaining issues
    remaining_errors = 0
    j = 0
    while j < len(fixed):
        try:
            fixed[j:j+4].decode("utf-8")
            j += 1
        except UnicodeDecodeError as e2:
            remaining_errors += 1
            pos = j + e2.start
            ctx = fixed[max(0,pos-20):pos+20]
            print(f"  Error at {pos}: {ctx!r}")
            j += e2.end
    print(f"Remaining errors: {remaining_errors}")

# Write result
with open(output, "wb") as f:
    f.write(fixed)

print(f"\nFixed file written: {output} ({len(fixed)} bytes)")

# Verify YAML
import yaml
with open(output, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

custom = config.get("subagents", {}).get("custom_agents", {})
print(f"Custom agents: {len(custom)}")
for name in custom:
    data = custom[name]
    has_prompt = "system_prompt" in data if isinstance(data, dict) else False
    status = "OK" if has_prompt else "MISSING system_prompt"
    print(f"  {name}: {status}")
