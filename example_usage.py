from video_analyzer import VideoAnalyzer

def example_usage():
    """
    使用示例
    """
    # 初始化分析器（请替换为你的实际API密钥）
    analyzer = VideoAnalyzer(
        api_key="YOUR_API_KEY",
        base_url="https://api.laozhang.ai/v1"
    )

    # 示例1: 分析在线视频
    print("=== 示例1: 分析在线视频 ===")
    video_url = "https://example.com/video.mp4"  # 替换为实际的视频URL
    text_prompt = "请详细描述这个视频的内容，包括场景、人物、动作等"

    try:
        result = analyzer.analyze_video_from_url(
            video_url=video_url,
            text_prompt=text_prompt
        )
        print("分析结果:")
        print(result)
    except Exception as e:
        print(f"分析失败: {e}")

    print("\n" + "="*50 + "\n")

    # 示例2: 自定义分析要求
    print("=== 示例2: 自定义分析要求 ===")
    custom_prompt = """请分析这个视频并提供以下信息：
    1. 视频的主要场景是什么？
    2. 视频中有哪些人物或物体？
    3. 视频的整体情绪如何？
    4. 视频的技术质量如何？"""

    try:
        result = analyzer.analyze_video_from_url(
            video_url=video_url,
            text_prompt=custom_prompt
        )
        print("详细分析结果:")
        print(result)
    except Exception as e:
        print(f"分析失败: {e}")

if __name__ == "__main__":
    example_usage()