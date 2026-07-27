#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度网盘自动上传脚本
文件会上传到 /apps/autobackup/ 目录
"""

import os
import sys
import glob
import requests

# 从环境变量读取
BAIDU_ACCESS_TOKEN = os.environ.get('BAIDU_ACCESS_TOKEN', '')

if not BAIDU_ACCESS_TOKEN:
    print("❌ 错误: 未设置 BAIDU_ACCESS_TOKEN")
    sys.exit(1)

# 查找要上传的文件
upload_dir = "./to_upload"
files_to_upload = glob.glob(f"{upload_dir}/*.zip")

if not files_to_upload:
    print("❌ 错误: 没有找到要上传的zip文件")
    sys.exit(1)

upload_file = files_to_upload[0]
file_size = os.path.getsize(upload_file)
file_name = os.path.basename(upload_file)
print(f"📦 找到文件: {file_name} ({file_size / 1024 / 1024:.2f} MB)")

print("=" * 50)
print("百度网盘自动上传脚本启动")
print("=" * 50)


def test_token(access_token):
    """测试Token是否有效"""
    test_url = "https://pan.baidu.com/rest/2.0/xpan/nas"
    params = {
        "method": "uinfo",
        "access_token": access_token
    }
    
    resp = requests.get(test_url, params=params)
    
    if resp.status_code == 200:
        result = resp.json()
        if result.get('errno') == 0:
            print(f"✅ Token有效，用户: {result.get('baidu_name')}")
            return True
        else:
            print(f"⚠️ Token测试失败: {result}")
            return False
    else:
        print(f"⚠️ Token测试失败: HTTP {resp.status_code}")
        return False


def upload_to_baidu(file_path, access_token):
    """上传文件到百度网盘"""
    
    upload_url = "https://c.pcs.baidu.com/rest/2.0/pcs/file"
    
    filename = os.path.basename(file_path)
    remote_path = f"/apps/autobackup/{filename}"
    
    params = {
        "method": "upload",
        "access_token": access_token,
        "path": remote_path,
        "ondup": "overwrite"
    }
    
    print(f"📤 正在上传到百度网盘...")
    print(f"   目标路径: {remote_path}")
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            resp = requests.post(upload_url, params=params, files=files, timeout=120)
        
        if resp.status_code == 200:
            result = resp.json()
            if result.get('error_code', 0) == 0:
                print(f"✅ 上传成功")
                return True
            else:
                print(f"❌ 上传失败: {result}")
                return False
        else:
            print(f"❌ 上传请求失败: HTTP {resp.status_code}")
            print(f"   响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 上传异常: {e}")
        return False


# 主流程
print("🔐 验证Token...")
if not test_token(BAIDU_ACCESS_TOKEN):
    print("❌ Token无效，请重新获取")
    print("   获取方法: https://openapi.baidu.com/oauth/2.0/authorize?response_type=token&client_id=你的AppKey&redirect_uri=oob&scope=basic,netdisk")
    sys.exit(1)

if upload_to_baidu(upload_file, BAIDU_ACCESS_TOKEN):
    print("=" * 50)
    print(f"✅ 文件 {file_name} 上传百度网盘完成")
    print(f"📁 存储位置: /apps/autobackup/")
    print("=" * 50)
    sys.exit(0)
else:
    print("❌ 上传失败")
    sys.exit(1)
