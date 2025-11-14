from video_analyzer import VideoAnalyzer

def quick_test():
    """
    快速测试视频分析功能
    """
    print("=== 快速测试视频分析工具 ===")
    print()

    # 使用已设置的API密钥
    analyzer = VideoAnalyzer()

    print("API配置已就绪，可以开始测试！")
    print()
    print("要进行实际测试，请提供以下信息：")
    print()

    # 示例测试 - 让用户输入
    try:
        video_url = input("请输入视频URL (或按回车跳过): ").strip()

        if video_url:
            text_prompt = input("请输入分析要求 (默认: 详细描述视频内容): ").strip()
            if not text_prompt:
                text_prompt = "请详细描述这个视频的内容"

            print(f"\n开始分析视频: {video_url}")
            print(f"分析要求: {text_prompt}")
            print("正在处理...")

            try:
                result = analyzer.analyze_video_from_url(
                    video_url=video_url,
                    text_prompt=text_prompt
                )

                print("\n=== 分析结果 ===")
                print(result)
                print("=" * 50)

            except Exception as e:
                print(f"\n❌ 分析失败: {str(e)}")
                print("请检查：")
                print("1. 视频URL是否可访问")
                print("2. API密钥是否有效")
                print("3. 网络连接是否正常")
        else:
            print("跳过测试，工具已准备就绪！")
            print()
            print("使用方法：")
            print("1. 设置环境变量: export VIDEO_ANALYZER_API_KEY='your_key'")
            print("2. 或者直接在代码中使用：")
            print()
            print("from video_analyzer import VideoAnalyzer")
            print("analyzer = VideoAnalyzer()")
            print("result = analyzer.analyze_video_from_url(")
            print("    video_url='your_video_url',")
            print("    text_prompt='你的分析要求'")
            print(")")
            print("print(result)")

    except KeyboardInterrupt:
        print("\n\n测试已取消")
    except EOFError:
        print("\n\n无法读取输入，请使用命令行参数或直接在代码中调用")

if __name__ == "__main__":
    quick_test()