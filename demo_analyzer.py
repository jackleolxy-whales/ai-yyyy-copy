from video_analyzer import VideoAnalyzer
import os

def demo_analyzer():
    """
    演示视频分析工具的功能
    """
    print("=== 视频分析工具演示 ===")
    print()

    # 检查是否设置了API密钥
    api_key = os.getenv("VIDEO_ANALYZER_API_KEY")
    if not api_key:
        print("⚠️  演示模式：未检测到API密钥")
        print("要实际使用，请设置环境变量或修改代码中的API密钥")
        print()
        print("设置方法：")
        print("export VIDEO_ANALYZER_API_KEY='your_actual_api_key'")
        print()
        print("或者在代码中直接设置...")
        demo_mode = True
    else:
        demo_mode = False

    # 初始化分析器
    if demo_mode:
        analyzer = VideoAnalyzer(api_key="demo_key", base_url="https://api.laozhang.ai/v1")
    else:
        analyzer = VideoAnalyzer(api_key=api_key, base_url="https://api.laozhang.ai/v1")

    print("1. 工具功能介绍：")
    print("   ✓ 支持在线视频URL分析")
    print("   ✓ 支持本地视频文件分析")
    print("   ✓ 自定义分析要求")
    print("   ✓ 多种视频格式支持")
    print("   ✓ 自动临时文件管理")
    print()

    print("2. 支持的视频格式：")
    formats = ["MP4", "AVI", "MOV", "WMV", "FLV", "WebM", "MKV"]
    print(f"   {', '.join(formats)}")
    print()

    print("3. URL验证测试：")
    test_urls = [
        ("https://example.com/video.mp4", "有效格式"),
        ("https://www.youtube.com/watch?v=example", "有效格式"),
        ("ftp://files.server.com/video.mov", "有效格式"),
        ("invalid-url", "无效格式"),
        ("not-a-url", "无效格式"),
    ]

    for url, description in test_urls:
        is_valid = analyzer.is_valid_url(url)
        status = "✓" if is_valid else "✗"
        print(f"   {status} {url} - {description}")

    print()

    if demo_mode:
        print("4. 演示模式 - 使用示例：")
        print()
        print("   要进行实际视频分析，请按以下步骤操作：")
        print()
        print("   步骤1: 设置API密钥")
        print("   export VIDEO_ANALYZER_API_KEY='your_actual_api_key'")
        print()
        print("   步骤2: 运行以下代码")
        print()

        example_code = '''
from video_analyzer import VideoAnalyzer

# 初始化
analyzer = VideoAnalyzer(api_key="your_actual_api_key")

# 分析在线视频
result = analyzer.analyze_video_from_url(
    video_url="https://example.com/your-video.mp4",
    text_prompt="请详细描述这个视频的内容，包括场景、人物、动作等"
)
print(result)

# 或者分析本地文件
result = analyzer.analyze_video_local(
    video_path="/path/to/your/video.mp4",
    text_prompt="请分析这个视频的技术质量和内容特点"
)
print(result)
        '''

        print(example_code)

    else:
        print("4. 实际测试模式：")
        print("   检测到API密钥，可以进行实际测试")
        print("   请提供一个视频URL来测试功能")

    print()
    print("=== 演示完成 ===")
    print("工具已准备就绪，设置API密钥后即可使用！")

if __name__ == "__main__":
    demo_analyzer()