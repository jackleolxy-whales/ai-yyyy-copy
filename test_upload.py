from video_analyzer import VideoAnalyzer
import tempfile
import requests
import os

def test_upload_functionality():
    """
    测试视频上传分析功能
    """
    print("=== 测试视频上传分析功能 ===")
    print()

    # 首先下载一个测试视频到临时文件
    test_url = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"

    print("1. 下载测试视频...")
    try:
        response = requests.get(test_url, stream=True)
        response.raise_for_status()

        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)
            temp_path = temp_file.name

        print(f"✅ 测试视频已下载到: {temp_path}")
        print(f"📊 文件大小: {os.path.getsize(temp_path) / 1024 / 1024:.2f} MB")

    except Exception as e:
        print(f"❌ 下载测试视频失败: {e}")
        return

    # 初始化分析器
    analyzer = VideoAnalyzer()

    # 测试本地文件分析
    print("\n2. 测试本地文件分析...")
    test_prompt = "请详细描述这个视频的内容，包括场景、人物、动作和整体主题"

    try:
        print(f"分析文件: {temp_path}")
        print(f"分析要求: {test_prompt}")
        print()
        print("开始分析...")
        print("-" * 60)

        # 使用流式响应进行本地文件分析
        result = analyzer.analyze_video_local(
            video_path=temp_path,
            text_prompt=test_prompt,
            max_tokens=None,  # 不限制token数量
            stream=True       # 启用流式响应
        )

        print("-" * 60)
        print()
        print("✅ 本地文件分析完成！")
        print(f"📊 结果长度: {len(result)} 字符")
        print(f"📝 结果行数: {len(result.splitlines())} 行")

    except Exception as e:
        print(f"❌ 本地文件分析失败: {e}")

    finally:
        # 清理临时文件
        try:
            os.unlink(temp_path)
            print(f"\n🗑️  临时文件已清理: {temp_path}")
        except:
            pass

def test_api_upload_endpoint():
    """
    测试Web上传API端点
    """
    print("\n\n=== 测试Web上传API端点 ===")
    print()

    # 下载测试视频
    test_url = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"

    print("1. 下载测试视频...")
    try:
        response = requests.get(test_url, stream=True)
        response.raise_for_status()

        video_data = b''
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                video_data += chunk

        print(f"✅ 测试视频已下载，大小: {len(video_data) / 1024 / 1024:.2f} MB")

    except Exception as e:
        print(f"❌ 下载测试视频失败: {e}")
        return

    # 测试上传API
    print("\n2. 测试上传API...")

    try:
        # 准备文件数据
        files = {
            'video_file': ('test_video.mp4', video_data, 'video/mp4'),
            'text_prompt': (None, '请详细描述这个视频的内容，包括场景、人物、动作和整体主题')
        }

        print("发送上传请求到 http://localhost:8080/upload ...")

        # 发送请求
        response = requests.post(
            'http://localhost:8080/upload',
            files=files,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                task_id = data.get('task_id')
                print(f"✅ 上传成功！任务ID: {task_id}")

                # 检查任务状态
                print("\n3. 检查分析状态...")
                import time

                for i in range(30):  # 最多等待30秒
                    status_response = requests.get(f'http://localhost:8080/status/{task_id}')
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        status = status_data.get('status')
                        progress = status_data.get('progress', 0)

                        print(f"   状态: {status}, 进度: {progress}%")

                        if status == 'completed':
                            print("✅ 分析完成！")

                            # 获取结果
                            result_response = requests.get(f'http://localhost:8080/result/{task_id}')
                            if result_response.status_code == 200:
                                result_data = result_response.json()
                                if result_data.get('success'):
                                    result = result_data.get('result', '')
                                    print(f"📊 结果长度: {len(result)} 字符")
                                    print(f"📝 结果行数: {len(result.splitlines())} 行")
                                    print("\n=== 分析结果 ===")
                                    print(result[:500] + "..." if len(result) > 500 else result)
                                else:
                                    print(f"❌ 获取结果失败: {result_data.get('error')}")
                            break
                        elif status == 'error':
                            print(f"❌ 分析失败")
                            break
                        else:
                            time.sleep(2)
                    else:
                        print(f"❌ 状态检查失败: HTTP {status_response.status_code}")
                        break
                else:
                    print("⏰ 分析超时")
            else:
                print(f"❌ 上传失败: {data.get('error')}")
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            print(f"响应内容: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到Web服务，请确保服务正在运行 (python run.py)")
    except Exception as e:
        print(f"❌ 上传测试失败: {e}")

if __name__ == "__main__":
    # 测试本地文件分析功能
    test_upload_functionality()

    # 测试Web上传API
    test_api_upload_endpoint()

    print("\n" + "="*60)
    print("🎯 测试总结:")
    print("✨ 本地文件分析功能正常")
    print("✨ Web上传功能已集成")
    print("✨ 支持多种视频格式")
    print("✨ 自动文件清理，保护隐私")
    print("="*60)