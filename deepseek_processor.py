import os
import json
from openai import OpenAI

class DeepSeekProcessor:
    def __init__(self):
        """初始化DeepSeek处理器"""
        self.client = OpenAI(
            api_key="sk-2d54294db37e431dbe0f917d4d1694f9",
            base_url="https://api.deepseek.com"
        )

        # 默认的JSON数据提取提示词
        self.default_prompt = """# Role

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

    def process_video_analysis_result(self, video_analysis_text, user_prompt=None, model="deepseek-reasoner", stream=False):
        """
        处理视频分析结果，调用DeepSeek进行第二步处理

        Args:
            video_analysis_text: 视频分析的结果文本
            user_prompt: 用户输入的提示词（默认使用JSON数据提取提示词）
            model: DeepSeek模型名称
            stream: 是否使用流式响应

        Returns:
            DeepSeek处理结果
        """
        try:
            # 使用默认提示词如果用户没有提供
            if user_prompt is None:
                user_prompt = self.default_prompt

            # 构建完整输入：用户提示词 + 视频分析结果
            full_input = f"{user_prompt}\n\n{video_analysis_text}"

            # 调用DeepSeek API
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": full_input}
                ],
                stream=stream
            )

            if stream:
                # 流式响应
                def generate():
                    for chunk in response:
                        if chunk.choices[0].delta.content is not None:
                            yield chunk.choices[0].delta.content
                return generate()
            else:
                # 非流式响应
                return response.choices[0].message.content

        except Exception as e:
            return f"DeepSeek处理错误: {str(e)}"

    def process_batch_results(self, video_analysis_results, user_prompt=None, model="deepseek-reasoner", stream=False):
        """
        批量处理多个视频分析结果

        Args:
            video_analysis_results: 视频分析结果列表
            user_prompt: 用户输入的提示词
            model: DeepSeek模型名称
            stream: 是否使用流式响应

        Returns:
            DeepSeek处理结果列表
        """
        results = []

        for i, analysis_result in enumerate(video_analysis_results):
            try:
                result = self.process_video_analysis_result(
                    analysis_result, user_prompt, model, stream
                )
                results.append({
                    "video_index": i,
                    "result": result
                })
            except Exception as e:
                results.append({
                    "video_index": i,
                    "error": f"视频{i+1}处理失败: {str(e)}"
                })

        return results

    def test_connection(self):
        """测试DeepSeek连接"""
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "user", "content": "Hello, test connection"}
                ],
                max_tokens=50
            )
            return True, response.choices[0].message.content
        except Exception as e:
            return False, str(e)