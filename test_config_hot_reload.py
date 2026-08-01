# -*- coding: utf-8 -*-
"""
配置热重载功能测试脚本
Test script for config hot-reload functionality
"""

import requests
import time
import yaml
import os

BASE_URL = "http://localhost:8000/api"
CONFIG_FILE = r"d:\Clash Verge\KikoeruTool-1.6.4\config\config.yaml"

def test_config_reload():
    """测试配置重新加载功能"""
    print("=" * 60)
    print("配置热重载功能测试")
    print("=" * 60)
    
    # 1. 获取当前配置
    print("\n[步骤 1] 获取当前配置...")
    response = requests.get(f"{BASE_URL}/config")
    if response.status_code != 200:
        print(f"✗ 获取配置失败：{response.status_code}")
        return False
    
    original_config = response.json()
    print(f"✓ 当前存储路径：{original_config.get('storage', {}).get('input_path', 'N/A')}")
    original_input_path = original_config.get('storage', {}).get('input_path', '/input')
    
    # 2. 修改配置文件
    print("\n[步骤 2] 直接修改配置文件...")
    test_path = f"/test_hot_reload_{int(time.time())}"
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # 保存原始值
        original_yaml_path = config_data.get('storage', {}).get('input_path', '/input')
        
        # 修改配置
        if 'storage' not in config_data:
            config_data['storage'] = {}
        config_data['storage']['input_path'] = test_path
        
        # 写入文件
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
        
        print(f"✓ 配置文件已修改，新路径：{test_path}")
    except Exception as e:
        print(f"✗ 修改配置文件失败：{e}")
        return False
    
    # 3. 等待配置文件监控器检测（给 watchdog 一些时间）
    print("\n[步骤 3] 等待配置文件监控器检测变更...")
    time.sleep(2)  # 给 watchdog 一些时间来检测和加载
    
    # 4. 再次获取配置（应该已经自动更新）
    print("\n[步骤 4] 获取更新后的配置（通过 API）...")
    response = requests.get(f"{BASE_URL}/config")
    if response.status_code != 200:
        print(f"✗ 获取配置失败：{response.status_code}")
        return False
    
    updated_config = response.json()
    new_input_path = updated_config.get('storage', {}).get('input_path', '/input')
    print(f"✓ 新的存储路径：{new_input_path}")
    
    # 5. 验证配置是否已更新
    print("\n[步骤 5] 验证配置是否已热重载...")
    if new_input_path == test_path:
        print("✓ 配置已成功热重载！（从配置文件直接读取）")
        success = True
    else:
        print(f"✗ 配置未自动更新，尝试手动调用 reload API...")
        
        # 调用 reload API
        reload_response = requests.post(f"{BASE_URL}/config/reload")
        if reload_response.status_code == 200:
            print("✓ 手动重载成功")
            
            # 再次检查配置
            response = requests.get(f"{BASE_URL}/config")
            final_config = response.json()
            final_input_path = final_config.get('storage', {}).get('input_path', '/input')
            
            if final_input_path == test_path:
                print("✓ 配置已通过 reload API 成功更新")
                success = True
            else:
                print(f"✗ 配置更新失败：期望 {test_path}, 实际 {final_input_path}")
                success = False
        else:
            print(f"✗ 手动重载失败：{reload_response.status_code}")
            success = False
    
    # 6. 恢复原始配置
    print("\n[步骤 6] 恢复原始配置...")
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        config_data['storage']['input_path'] = original_yaml_path
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
        
        print(f"✓ 配置已恢复为：{original_yaml_path}")
        
        # 等待自动重载
        time.sleep(2)
        
    except Exception as e:
        print(f"✗ 恢复配置失败：{e}")
    
    print("\n" + "=" * 60)
    if success:
        print("✓ 配置热重载功能测试通过！")
    else:
        print("✗ 配置热重载功能测试失败！")
    print("=" * 60)
    
    return success

if __name__ == '__main__':
    try:
        # 检查服务是否运行
        print("检查服务是否运行...")
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code != 200:
            print("✗ 服务未运行或响应异常")
            exit(1)
        print("✓ 服务运行正常\n")
        
        # 运行测试
        test_config_reload()
        
    except requests.exceptions.ConnectionError:
        print("✗ 无法连接到服务器，请确保服务正在运行")
        exit(1)
    except Exception as e:
        print(f"✗ 测试过程中发生错误：{e}")
        exit(1)
