from video_analyzer import VideoAnalyzer

def test_video_analyzer():
    """
    测试视频分析工具
    """
    print("=== 视频分析工具测试 ===")
    print()

    # 初始化分析器（请替换为你的实际API密钥）
    api_key = "YOUR_API_KEY"  # 请替换为实际API密钥
    base_url = "https://api.laozhang.ai/v1"

    if api_key == "YOUR_API_KEY":
        print("⚠️  请先在代码中设置你的API密钥！")
        print("在 video_analyzer.py 或此文件中将 'YOUR_API_KEY' 替换为实际密钥")
        return

    analyzer = VideoAnalyzer(api_key=api_key, base_url=base_url)

    # 测试用例1: 验证URL功能
    print("1. 测试URL验证功能...")
    test_urls = [
        "https://example.com/video.mp4",  # 有效格式
        "invalid-url",  # 无效格式
        "ftp://test.com/video.mp4",  # 有效格式
    ]

    for url in test_urls:
        is_valid = analyzer.is_valid_url(url)
        print(f"   URL: {url} -> {'有效' if is_valid else '无效'}")

    print()

    # 测试用例2: 示例视频分析（需要实际API密钥）
    print("2. 视频分析示例...")
    print("   要进行实际测试，请：")
    print("   a) 设置有效的API密钥")
    print("   b) 提供一个可访问的视频URL")
    print()

    # 示例代码（注释掉，避免实际调用）
    example_code = '''
    # 实际使用示例：
    try:
        result = analyzer.analyze_video_from_url(
            video_url="https://your-video-url.mp4",
            text_prompt="请详细描述这个视频的内容"
        )
        print("分析结果:")
        print(result)
    except Exception as e:
        print(f"分析失败: {e}")
    '''

    print("   示例代码：")
    print(example_code)

    print()

    # 测试用例3: 本地文件分析示例
    print("3. 本地文件分析示例...")
    print("   要测试本地文件分析，请：")
    print("   a) 设置有效的API密钥")
    print("   b) 提供本地视频文件路径")

    example_local_code = '''
    # 本地文件分析示例：
    try:
        result = analyzer.analyze_video_local(
            video_path="/path/to/your/video.mp4",
            text_prompt="请分析这个视频的技术质量"
        )
        print("分析结果:")
        print(result)
    except Exception as e:
        print(f"分析失败: {e}")
    '''

    print("   示例代码：")
    print(example_local_code)

    print()
    print("=== 测试完成 ===")
    print("工具已准备就绪，设置API密钥后即可使用！")

if __name__ == "__main__":
    test_video_analyzer()