#!/usr/bin/env python
"""测试本地模型配置是否正确加载"""

import sys
import os

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from deerflow.config import get_app_config

def test_local_model_config():
    """测试本地模型配置"""
    config = get_app_config()
    
    # 查找 qwen-3-6-local 模型配置
    local_model = None
    for model in config.models:
        if model.name == 'qwen-3-6-local':
            local_model = model
            break
    
    if not local_model:
        print("❌ 未找到 qwen-3-6-local 模型配置")
        return False
    
    print("[OK] 找到本地模型配置:")
    print(f"   模型名称: {local_model.name}")
    print(f"   基础URL: {local_model.base_url}")
    print(f"   最大重试次数: {local_model.max_retries}")
    print(f"   最大输出Token: {local_model.max_tokens}")
    print(f"   温度: {local_model.temperature}")
    print(f"   上下文窗口: {local_model.context_window}")
    
    # 检查 model_kwargs
    if hasattr(local_model, 'model_kwargs') and local_model.model_kwargs:
        print("\n   模型参数 (model_kwargs):")
        for key, value in local_model.model_kwargs.items():
            print(f"     {key}: {value}")
        
        # 检查 extra_body
        if 'extra_body' in local_model.model_kwargs:
            extra_body = local_model.model_kwargs['extra_body']
            print("\n   额外请求体参数 (extra_body):")
            for key, value in extra_body.items():
                print(f"     {key}: {value}")
            
            # 验证关键参数
            checks = []
            if 'repetition_penalty' in extra_body:
                rep_penalty = extra_body['repetition_penalty']
                if rep_penalty >= 1.15 and rep_penalty <= 1.3:
                    checks.append(f"[OK] repetition_penalty={rep_penalty} (在推荐范围内)")
                else:
                    checks.append(f"[WARN] repetition_penalty={rep_penalty} (建议范围 1.15-1.3)")
            
            if 'presence_penalty' in extra_body:
                checks.append(f"[OK] presence_penalty={extra_body['presence_penalty']}")
            
            if 'frequency_penalty' in extra_body:
                checks.append(f"[OK] frequency_penalty={extra_body['frequency_penalty']}")
            
            print("\n   配置检查:")
            for check in checks:
                print(f"     {check}")
    
    # 验证关键配置项
    print("\n[CHECK] 关键配置验证:")
    issues = []
    
    if local_model.max_tokens is None or local_model.max_tokens < 8000:
        issues.append("⚠️ max_tokens 未设置或过小，可能导致无限生成")
    else:
        print(f"   ✅ max_tokens={local_model.max_tokens} (输出限制已设置)")
    
    if local_model.temperature > 0.7:
        issues.append("⚠️ temperature 偏高，建议降低到 0.5-0.6")
    else:
        print(f"   ✅ temperature={local_model.temperature} (随机性控制合理)")
    
    if local_model.max_retries > 2:
        issues.append("⚠️ max_retries 过高，本地模型建议设为 1")
    else:
        print(f"   ✅ max_retries={local_model.max_retries} (重试次数合理)")
    
    if issues:
        print("\n🔧 优化建议:")
        for issue in issues:
            print(f"   {issue}")
        return False
    else:
        print("\n✅ 配置正常，本地模型循环问题应该已解决！")
        return True

if __name__ == "__main__":
    success = test_local_model_config()
    sys.exit(0 if success else 1)
