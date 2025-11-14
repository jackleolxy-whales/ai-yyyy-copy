from video_analyzer import VideoAnalyzer

def test_streaming_analysis():
    """
    测试流式响应功能
    """
    print("=== 测试流式视频分析 ===")
    print()

    # 初始化分析器
    analyzer = VideoAnalyzer()

    # 测试URL
    test_url = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
    test_prompt = "请详细描述这个视频的内容，包括场景、人物、动作和整体主题，尽可能提供详细的分析"

    print(f"测试视频: {test_url}")
    print(f"分析要求: {test_prompt}")
    print()
    print("开始流式分析...")
    print("-" * 60)

    try:
        # 使用流式响应进行分析
        result = analyzer.analyze_video_from_url(
            video_url=test_url,
            text_prompt=test_prompt,
            max_tokens=None,  # 不限制token数量
            stream=True       # 启用流式响应
        )

        print("-" * 60)
        print()
        print("✅ 流式分析完成！")
        print(f"📊 结果长度: {len(result)} 字符")
        print(f"📝 结果行数: {len(result.splitlines())} 行")
        print()
        print("=== 完整分析结果 ===")
        print(result)

    except Exception as e:
        print(f"❌ 分析失败: {e}")

def test_non_streaming_analysis():
    """
    测试非流式响应功能（对比）
    """
    print("\n\n=== 测试非流式视频分析（对比） ===")
    print()

    # 初始化分析器
    analyzer = VideoAnalyzer()

    # 测试URL
    test_url = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
    test_prompt = "请详细描述这个视频的内容，包括场景、人物、动作和整体主题，尽可能提供详细的分析"

    print(f"测试视频: {test_url}")
    print(f"分析要求: {test_prompt}")
    print()
    print("开始非流式分析...")
    print("-" * 60)

    try:
        # 使用非流式响应进行分析
        result = analyzer.analyze_video_from_url(
            video_url=test_url,
            text_prompt=test_prompt,
            max_tokens=None,  # 不限制token数量
            stream=False      # 非流式响应
        )

        print("-" * 60)
        print()
        print("✅ 非流式分析完成！")
        print(f"📊 结果长度: {len(result)} 字符")
        print(f"📝 结果行数: {len(result.splitlines())} 行")

    except Exception as e:
        print(f"❌ 分析失败: {e}")

if __name__ == "__main__":
    # 测试流式响应
    test_streaming_analysis()

    # 测试非流式响应作为对比
    test_non_streaming_analysis()

    print("\n" + "="*60)
    print("🎯 测试总结:")
    print("✨ 流式响应可以实时看到分析过程")
    print("✨ 移除了max_tokens限制，可以获得完整结果")
    print("✨ 现在应该能看到更详细的视频分析内容")
    print("="*60)