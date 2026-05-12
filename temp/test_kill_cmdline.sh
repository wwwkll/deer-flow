#!/usr/bin/env bash
# 测试补丁的 _windows_kill_by_cmdline 函数引号是否正确（只查不杀）
# 这才是真实场景：bash 直接执行，没有外层 -c 包装

# 改 Stop-Process 为 Select-Object 看效果
_windows_check_by_cmdline() {
    local pattern="$1"
    powershell.exe -NoProfile -NonInteractive -Command \
        "Get-CimInstance Win32_Process -Filter 'CommandLine LIKE ''%${pattern}%''' -ErrorAction SilentlyContinue | Where-Object { \$_.Name -in 'uv.exe','python.exe','node.exe','langgraph.exe','uvicorn.exe' } | Select-Object ProcessId, Name | Format-Table -AutoSize"
}

echo "===== Test 1: langgraph dev ====="
_windows_check_by_cmdline "langgraph dev"

echo "===== Test 2: uvicorn app.gateway.app:app ====="
_windows_check_by_cmdline "uvicorn app.gateway.app:app"

echo "===== Test 3: next dev ====="
_windows_check_by_cmdline "next dev"

echo "===== Done ====="
