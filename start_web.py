#!/usr/bin/env python3
"""
视频分析Web服务启动脚本
"""

import os
import sys
import subprocess
import webbrowser
import time
from threading import Timer

def check_dependencies():
    """检查依赖是否已安装"""
    required_packages = ['flask', 'openai', 'requests']
    missing_packages = []

    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print("❌ 缺少以下依赖包:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n请运行以下命令安装依赖:")
        print("pip install -r requirements.txt")
        return False

    print("✅ 所有依赖包已安装")
    return True

def open_browser():
    """延迟打开浏览器"""
    time.sleep(2)
    webbrowser.open('http://localhost:5000')

def main():
    print("🚀 视频分析Web服务启动器")
    print("=" * 50)

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 检查API密钥
    from video_analyzer import VideoAnalyzer
    try:
        analyzer = VideoAnalyzer()
        print("✅ API配置检查通过")
    except Exception as e:
        print(f"❌ API配置检查失败: {e}")
        print("请检查video_analyzer.py中的API密钥配置")
        sys.exit(1)

    print("\n🌐 正在启动Web服务...")
    print("📱 服务将在 http://localhost:5001 上运行")
    print("⚠️  按 Ctrl+C 停止服务")
    print("=" * 50)

    # 设置延迟打开浏览器
    Timer(2, open_browser).start()

    try:
        # 启动Flask应用
        from app import app
        app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\n👋 服务已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()