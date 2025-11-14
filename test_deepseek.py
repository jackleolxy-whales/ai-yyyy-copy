#!/usr/bin/env python3
"""
DeepSeek处理功能测试脚本
"""

from deepseek_processor import DeepSeekProcessor

def test_deepseek_processor():
    """测试DeepSeek处理器"""
    print("🧠 测试DeepSeek处理器...")

    # 初始化处理器
    processor = DeepSeekProcessor()

    # 测试连接
    print("1. 测试API连接...")
    success, result = processor.test_connection()
    if success:
        print("✅ API连接成功")
        print(f"   测试结果: {result}")
    else:
        print(f"❌ API连接失败: {result}")
        return

    # 测试视频分析结果处理
    print("\n2. 测试视频分析结果处理...")

    # 模拟视频分析结果（包含eventBreakdown的JSON数据）
    mock_video_analysis = '''
    {
        "eventBreakdown": [
            {
                "timestamp": "00:00:01",
                "event": "视频开始",
                "description": "视频开头场景"
            },
            {
                "timestamp": "00:00:15",
                "event": "主要动作",
                "description": "关键内容展示"
            },
            {
                "timestamp": "00:01:30",
                "event": "结束画面",
                "description": "视频结尾"
            }
        ],
        "summary": "这是一个测试视频的完整分析结果"
    }
    '''

    # 默认的JSON提取提示词
    default_prompt = """# Role

You are a JSON data processing engine.

# Core Directive

Your sole task is to parse the JSON data provided by the user. You are strictly forbidden from performing any web searches, information lookups, or using any information from your knowledge base unrelated to this JSON. You must operate *only* on the provided JSON text.

# Task

1.  Receive the JSON data provided by the user.

2.  Locate the array named `eventBreakdown` within the JSON data.

3.  Iterate through every object within the `eventBreakdown` array.

4.  From each object, extract the value associated with the `timestamp` key.

5.  Collect all extracted `timestamp` values into a JSON string array, maintaining their original order of appearance.

# Output Constraints (!!! Must Be Strictly Followed !!!)

-   Your final response **must** be *only* the JSON array itself.

-   You **must not** include any explanatory text (e.g., "Here is the data you requested...").

-   You **must not** include any Markdown formatting (e.g., ```json ... ```).

-   Your response must begin directly with `[` and end directly with `]`.

# Example (For your internal understanding only; do not output)

If the input JSON contains:

`"eventBreakdown": [{"timestamp": "A"}, {"timestamp": "B"}]`

Your one and only output must be:

`["A", "B"]`

Now, I give you the user's JSON data: """

    try:
        print("   发送处理请求...")
        result = processor.process_video_analysis_result(
            video_analysis_text=mock_video_analysis,
            user_prompt=default_prompt,
            model="deepseek-reasoner",
            stream=False
        )

        print("✅ 处理成功！")
        print("   提取的时间戳数组:")
        print(f"   {result}")

        # 验证结果是否为有效的JSON数组
        import json
        try:
            timestamps = json.loads(result)
            if isinstance(timestamps, list):
                print(f"✅ 成功提取 {len(timestamps)} 个时间戳")
                for i, ts in enumerate(timestamps):
                    print(f"     {i+1}. {ts}")
            else:
                print("❌ 结果不是数组格式")
        except json.JSONDecodeError:
            print("⚠️  结果不是有效的JSON格式")
            print(f"   原始结果: {result}")

    except Exception as e:
        print(f"❌ 处理失败: {e}")

    # 测试批量处理
    print("\n3. 测试批量处理...")

    mock_results = [
        mock_video_analysis,
        '''
        {
            "eventBreakdown": [
                {
                    "timestamp": "00:00:05",
                    "event": "场景1"
                },
                {
                    "timestamp": "00:00:25",
                    "event": "场景2"
                }
            ]
        }
        '''
    ]

    try:
        print("   发送批量处理请求...")
        results = processor.process_batch_results(
            video_analysis_results=mock_results,
            user_prompt=default_prompt,
            model="deepseek-reasoner",
            stream=False
        )

        print("✅ 批量处理成功！")
        for i, result in enumerate(results):
            print(f"   视频 {i+1} 结果:")
            if result.get("success"):
                print(f"     {result.get('result')}")
            else:
                print(f"     ❌ 错误: {result.get('error')}")

    except Exception as e:
        print(f"❌ 批量处理失败: {e}")

def main():
    print("🧪 DeepSeek处理功能测试")
    print("=" * 50)

    try:
        test_deepseek_processor()
        print("\n✅ 测试完成！")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")

if __name__ == "__main__":
    main()