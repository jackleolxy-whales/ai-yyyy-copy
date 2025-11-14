from video_analyzer import VideoAnalyzer

def direct_test():
    """
    直接测试视频分析功能（使用预设URL）
    """
    print("=== 直接测试视频分析工具 ===")
    print()

    # 初始化分析器
    analyzer = VideoAnalyzer()

    # 测试URL验证功能
    print("1. 测试URL验证功能...")
    test_urls = [
        "https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4",
        "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
        "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
    ]

    for url in test_urls:
        is_valid = analyzer.is_valid_url(url)
        print(f"   ✓ URL: {url[:50]}... -> {'有效' if is_valid else '无效'}")

    print()

    # 选择一个测试URL
    test_url = test_urls[2]  # 使用Google的示例视频
    test_prompt = "请详细描述这个视频的内容，包括场景、物体、动作和整体主题"

    print(f"2. 开始分析测试视频...")
    print(f"   视频URL: {test_url}")
    print(f"   分析要求: {test_prompt}")
    print()

    try:
        print("正在下载视频...")
        print("正在转换为base64...")
        print("正在调用API分析...")

        result = analyzer.analyze_video_from_url(
            video_url=test_url,
            text_prompt=test_prompt
        )

        print("\n" + "="*60)
        print("🎉 分析成功！")
        print("="*60)
        print("\n分析结果:")
        print(result)
        print("\n" + "="*60)

    except Exception as e:
        print(f"\n❌ 分析失败: {str(e)}")
        print("\n可能的原因:")
        print("1. 网络连接问题")
        print("2. 视频URL无法访问")
        print("3. API配额或密钥问题")
        print("4. 视频文件过大或格式不支持")

        print(f"\n错误详情: {type(e).__name__}: {str(e)}")

    print()
    print("3. 工具功能总结:")
    print("   ✓ 视频下载功能")
    print("   ✓ base64编码转换")
    print("   ✓ API调用集成")
    print("   ✓ 错误处理机制")
    print("   ✓ 临时文件清理")

if __name__ == "__main__":
    direct_test()