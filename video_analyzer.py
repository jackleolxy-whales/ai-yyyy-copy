import base64
import requests
from openai import OpenAI
import os
from urllib.parse import urlparse
import tempfile
import re

class VideoAnalyzer:
    def __init__(self, api_key="sk-9etwRjexuGoZ3txK3766701eC7Fa4fB4906c0cF9D46cC5B2", base_url="https://api.laozhang.ai/v1"):
        """
        初始化视频分析器

        Args:
            api_key: API密钥
            base_url: API基础URL
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

    def is_valid_url(self, url):
        """验证URL是否有效"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    def download_video_from_url(self, video_url, timeout=30):
        """
        从URL下载视频文件

        Args:
            video_url: 视频URL
            timeout: 下载超时时间（秒）

        Returns:
            str: 下载的临时文件路径
        """
        try:
            # 发送请求下载视频
            response = requests.get(video_url, stream=True, timeout=timeout)
            response.raise_for_status()

            # 获取文件扩展名
            content_type = response.headers.get('content-type', '')
            if 'video' not in content_type:
                raise ValueError(f"URL不指向视频文件，内容类型: {content_type}")

            # 根据Content-Type确定扩展名
            extension_map = {
                'video/mp4': '.mp4',
                'video/avi': '.avi',
                'video/mov': '.mov',
                'video/wmv': '.wmv',
                'video/flv': '.flv',
                'video/webm': '.webm',
                'video/mkv': '.mkv'
            }

            extension = extension_map.get(content_type, '.mp4')

            # 创建临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                return temp_file.name

        except requests.exceptions.RequestException as e:
            raise ValueError(f"下载视频失败: {str(e)}")
        except Exception as e:
            raise ValueError(f"处理视频文件时出错: {str(e)}")

    def video_to_base64(self, video_path):
        """
        将视频文件转换为base64编码

        Args:
            video_path: 视频文件路径

        Returns:
            str: base64编码的视频数据
        """
        try:
            with open(video_path, "rb") as video_file:
                video_data = video_file.read()
                return base64.b64encode(video_data).decode('utf-8')
        except Exception as e:
            raise ValueError(f"转换视频为base64失败: {str(e)}")

    def get_video_mime_type(self, video_path):
        """
        获取视频的MIME类型

        Args:
            video_path: 视频文件路径

        Returns:
            str: MIME类型
        """
        # 简单的文件扩展名映射
        extension = os.path.splitext(video_path)[1].lower()
        mime_map = {
            '.mp4': 'video/mp4',
            '.avi': 'video/avi',
            '.mov': 'video/mov',
            '.wmv': 'video/wmv',
            '.flv': 'video/flv',
            '.webm': 'video/webm',
            '.mkv': 'video/mkv'
        }
        return mime_map.get(extension, 'video/mp4')

    def analyze_video_from_url(self, video_url, text_prompt="请详细描述这个视频的内容", model="gemini-2.5-flash", max_tokens=None, stream=False):
        """
        从在线URL分析视频内容

        Args:
            video_url: 视频的在线URL
            text_prompt: 分析要求的文字描述
            model: 使用的模型名称
            max_tokens: 最大token数（None表示无限制）
            stream: 是否使用流式响应

        Returns:
            str: 视频分析结果
        """
        # 验证URL
        if not self.is_valid_url(video_url):
            raise ValueError("无效的视频URL")

        # 下载视频
        print(f"正在下载视频: {video_url}")
        temp_video_path = self.download_video_from_url(video_url)

        try:
            # 转换为base64
            print("正在转换视频为base64编码...")
            base64_video = self.video_to_base64(temp_video_path)

            # 获取MIME类型
            mime_type = self.get_video_mime_type(temp_video_path)

            # 调用API分析视频
            print("正在分析视频内容...")

            # 构建请求参数
            params = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": text_prompt},
                            {
                                "type": "video_url",
                                "video_url": {
                                    "url": f"data:{mime_type};base64,{base64_video}"
                                }
                            }
                        ]
                    }
                ],
                "stream": stream
            }

            # 只有在指定max_tokens时才添加
            if max_tokens is not None:
                params["max_tokens"] = max_tokens

            if stream:
                # 流式响应处理
                full_response = ""
                response = self.client.chat.completions.create(**params)

                print("正在接收流式响应...")
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        print(content, end='', flush=True)  # 实时输出

                print()  # 换行
                return full_response
            else:
                # 非流式响应处理
                response = self.client.chat.completions.create(**params)
                return response.choices[0].message.content

        finally:
            # 清理临时文件
            try:
                os.unlink(temp_video_path)
                print("临时文件已清理")
            except:
                pass

    def analyze_video_local(self, video_path, text_prompt="请详细描述这个视频的内容", model="gemini-2.5-flash", max_tokens=None, stream=False):
        """
        分析本地视频文件

        Args:
            video_path: 本地视频文件路径
            text_prompt: 分析要求的文字描述
            model: 使用的模型名称
            max_tokens: 最大token数（None表示无限制）
            stream: 是否使用流式响应

        Returns:
            str: 视频分析结果
        """
        if not os.path.exists(video_path):
            raise ValueError("视频文件不存在")

        # 转换为base64
        print("正在转换视频为base64编码...")
        base64_video = self.video_to_base64(video_path)

        # 获取MIME类型
        mime_type = self.get_video_mime_type(video_path)

        # 调用API分析视频
        print("正在分析视频内容...")

        # 构建请求参数
        params = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {
                            "type": "video_url",
                            "video_url": {
                                "url": f"data:{mime_type};base64,{base64_video}"
                            }
                        }
                    ]
                }
            ],
            "stream": stream
        }

        # 只有在指定max_tokens时才添加
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        if stream:
            # 流式响应处理
            full_response = ""
            response = self.client.chat.completions.create(**params)

            print("正在接收流式响应...")
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    print(content, end='', flush=True)  # 实时输出

            print()  # 换行
            return full_response
        else:
            # 非流式响应处理
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content


def main():
    """
    主函数 - 命令行交互界面
    """
    print("=== 视频内容分析工具 ===")
    print("支持在线URL和本地文件")
    print()

    # 初始化分析器
    api_key = os.getenv("VIDEO_ANALYZER_API_KEY", "YOUR_API_KEY")
    base_url = os.getenv("VIDEO_ANALYZER_BASE_URL", "https://api.laozhang.ai/v1")

    analyzer = VideoAnalyzer(api_key=api_key, base_url=base_url)

    while True:
        print("\n请选择操作:")
        print("1. 分析在线视频URL")
        print("2. 分析本地视频文件")
        print("3. 退出")

        choice = input("\n请输入选择 (1-3): ").strip()

        if choice == "1":
            try:
                video_url = input("请输入视频URL: ").strip()
                text_prompt = input("请输入分析要求 (默认: 详细描述视频内容): ").strip()

                if not text_prompt:
                    text_prompt = "请详细描述这个视频的内容"

                print(f"\n开始分析视频: {video_url}")
                result = analyzer.analyze_video_from_url(video_url, text_prompt)

                print("\n=== 分析结果 ===")
                print(result)
                print("=" * 50)

            except Exception as e:
                print(f"分析失败: {str(e)}")

        elif choice == "2":
            try:
                video_path = input("请输入本地视频文件路径: ").strip()
                text_prompt = input("请输入分析要求 (默认: 详细描述视频内容): ").strip()

                if not text_prompt:
                    text_prompt = "请详细描述这个视频的内容"

                print(f"\n开始分析视频: {video_path}")
                result = analyzer.analyze_video_local(video_path, text_prompt)

                print("\n=== 分析结果 ===")
                print(result)
                print("=" * 50)

            except Exception as e:
                print(f"分析失败: {str(e)}")

        elif choice == "3":
            print("感谢使用！")
            break

        else:
            print("无效选择，请重新输入")


if __name__ == "__main__":
    main()