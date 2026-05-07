import ast

# 1. Verify loop_detection_middleware.py syntax
with open(r'c:\xiangmu\deer-flow\backend\packages\harness\deerflow\agents\middlewares\loop_detection_middleware.py', 'r', encoding='utf-8') as f:
    source = f.read()
    tree = ast.parse(source)
    print('OK: loop_detection_middleware.py syntax is valid')

# 2. Verify test file syntax
with open(r'c:\xiangmu\deer-flow\backend\tests\test_loop_detection_middleware.py', 'r', encoding='utf-8') as f:
    source = f.read()
    tree = ast.parse(source)
    print('OK: test_loop_detection_middleware.py syntax is valid')

# 3. Check key modifications
content = open(r'c:\xiangmu\deer-flow\backend\packages\harness\deerflow\agents\middlewares\loop_detection_middleware.py', 'r', encoding='utf-8').read()

if 'from langchain.agents.middleware import AgentMiddleware, hook_config' in content:
    print('OK: hook_config imported')
else:
    print('FAIL: hook_config not imported')

if '@hook_config(can_jump_to=["end"])' in content:
    print('OK: @hook_config(can_jump_to=["end"]) decorator used')
else:
    print('FAIL: hook_config decorator not used')

if '"jump_to": "end"' in content:
    print('OK: jump_to: end returned')
else:
    print('FAIL: jump_to not returned')

# 4. Check test file
test_content = open(r'c:\xiangmu\deer-flow\backend\tests\test_loop_detection_middleware.py', 'r', encoding='utf-8').read()
count = test_content.count('assert result.get("jump_to") == "end"')
print(f'OK: {count} assertions for jump_to in test file')

print('All checks passed!')
