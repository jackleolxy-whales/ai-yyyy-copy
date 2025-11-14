#!/usr/bin/env python3
"""
简化版启动脚本 - 直接启动Web服务
"""

if __name__ == "__main__":
    print("🚀 启动视频分析Web服务...")
    print("📱 浏览器将自动打开 http://localhost:8080")
    print("⚠️  按 Ctrl+C 停止服务\n")

    try:
        from app import app
        import webbrowser
        import threading
        import time

        def open_browser():
            time.sleep(1.5)
            webbrowser.open('http://localhost:8080')

        # 在后台线程中打开浏览器
        threading.Thread(target=open_browser, daemon=True).start()

        # 启动Flask应用
        app.run(host='0.0.0.0', port=8080, debug=False)

    except KeyboardInterrupt:
        print("\n👋 服务已停止")
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
    except Exception as e:
        print(f"❌ 启动失败: {e}")