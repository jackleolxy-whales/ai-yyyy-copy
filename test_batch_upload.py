import requests
import tempfile
import os

def test_batch_upload():
    """
    测试批量上传功能
    """
    print("=== 测试批量视频上传功能 ===")
    print()

    # 下载多个测试视频
    test_urls = [
        "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
        "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4"
    ]

    temp_files = []

    try:
        print("1. 下载测试视频...")
        for i, url in enumerate(test_urls):
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix=f'_test_{i}.mp4', delete=False) as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_files.append(temp_file.name)
                print(f"   ✅ 视频 {i+1} 已下载: {os.path.basename(temp_file.name)} ({os.path.getsize(temp_file.name) / 1024 / 1024:.2f} MB)")

        print(f"\n2. 测试批量上传API...")

        # 准备文件数据
        files = []
        for i, temp_file in enumerate(temp_files):
            filename = f"test_video_{i+1}.mp4"
            with open(temp_file, 'rb') as f:
                file_content = f.read()
            files.append(('video_files', (filename, file_content, 'video/mp4')))

        # 添加分析要求
        form_data = {
            'text_prompt': '请详细描述这个视频的内容，包括场景、人物、动作和整体主题'
        }

        print("   发送批量上传请求...")
        response = requests.post(
            'http://localhost:8080/upload/batch',
            files=files,
            data=form_data,
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                batch_id = data.get('batch_id')
                tasks = data.get('tasks', [])
                total_files = data.get('total_files', 0)

                print(f"   ✅ 批量上传成功！")
                print(f"   📊 批次ID: {batch_id}")
                print(f"   📁 文件数量: {total_files}")
                print(f"   📋 任务列表:")

                for task in tasks:
                    print(f"      - {task['filename']} (任务ID: {task['task_id']})")

                # 检查批次状态
                print(f"\n3. 检查批次分析状态...")
                import time

                for attempt in range(60):  # 最多等待2分钟
                    status_response = requests.get(f'http://localhost:8080/batch/status/{batch_id}')
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        overall_status = status_data.get('overall_status')
                        overall_progress = status_data.get('overall_progress', 0)
                        total_tasks = status_data.get('total_tasks', 0)
                        completed_count = status_data.get('completed_count', 0)
                        error_count = status_data.get('error_count', 0)

                        print(f"   状态: {overall_status}, 进度: {overall_progress}% ({completed_count + error_count}/{total_tasks})")

                        if overall_status in ['completed', 'completed_with_errors']:
                            print("   ✅ 批量分析完成！")

                            # 获取结果
                            print(f"\n4. 获取批量分析结果...")
                            result_response = requests.get(f'http://localhost:8080/batch/results/{batch_id}')
                            if result_response.status_code == 200:
                                result_data = result_response.json()
                                if result_data.get('success'):
                                    results = result_data.get('results', {})
                                    total_count = result_data.get('total_count', 0)

                                    print(f"   📊 结果总数: {total_count}")
                                    print(f"   📄 分析结果:")

                                    for task_id, result in results.items():
                                        filename = result.get('filename', '未知文件')
                                        success = result.get('success', False)

                                        print(f"\n   📹 文件: {filename}")
                                        if success:
                                            analysis_result = result.get('result', '')
                                            print(f"   ✅ 分析成功 (长度: {len(analysis_result)} 字符)")
                                            print(f"   📝 前200字符预览:")
                                            print(f"   {analysis_result[:200]}...")
                                        else:
                                            error_msg = result.get('error', '未知错误')
                                            print(f"   ❌ 分析失败: {error_msg}")
                                else:
                                    print(f"   ❌ 获取结果失败: {result_data.get('error')}")
                            break
                        else:
                            time.sleep(2)
                    else:
                        print(f"   ❌ 状态检查失败: HTTP {status_response.status_code}")
                        break
                else:
                    print("   ⏰ 批量分析超时")
            else:
                print(f"   ❌ 批量上传失败: {data.get('error')}")
        else:
            print(f"   ❌ HTTP错误: {response.status_code}")
            print(f"   响应内容: {response.text}")

    except requests.exceptions.ConnectionError:
        print("   ❌ 无法连接到Web服务，请确保服务正在运行 (python run.py)")
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")

    finally:
        # 清理临时文件
        print(f"\n5. 清理临时文件...")
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
                print(f"   🗑️  已删除: {os.path.basename(temp_file)}")
            except:
                pass

def test_batch_validation():
    """
    测试批量上传验证功能
    """
    print("\n\n=== 测试批量上传验证功能 ===")
    print()

    try:
        # 测试文件数量超限
        print("1. 测试文件数量超限...")
        files = []
        for i in range(12):  # 超过10个文件限制
            files.append(('video_files', (f'test_{i}.mp4', b'fake content', 'video/mp4')))

        response = requests.post(
            'http://localhost:8080/upload/batch',
            files=files,
            data={'text_prompt': '测试'},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if not data.get('success'):
                print(f"   ✅ 正确检测到文件数量超限: {data.get('error')}")
            else:
                print(f"   ❌ 未能检测到文件数量超限")
        else:
            print(f"   ❌ 请求失败: HTTP {response.status_code}")

    except Exception as e:
        print(f"   ❌ 验证测试失败: {e}")

if __name__ == "__main__":
    # 测试批量上传功能
    test_batch_upload()

    # 测试验证功能
    test_batch_validation()

    print("\n" + "="*60)
    print("🎯 批量上传功能测试总结:")
    print("✨ 支持同时上传多个视频文件")
    print("✨ 分别调用API进行独立分析")
    print("✨ 批次状态跟踪和进度监控")
    print("✨ 分区域展示分析结果")
    print("✨ 完整的错误处理和验证")
    print("="*60)