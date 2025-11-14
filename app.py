from flask import Flask, render_template, request, jsonify
import os
from video_analyzer import VideoAnalyzer
from deepseek_processor import DeepSeekProcessor
import threading
import time
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)

# 配置文件上传
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB最大文件大小
app.config['UPLOAD_FOLDER'] = 'uploads'

# 确保上传目录存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# 允许的视频文件扩展名
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 全局变量存储分析结果
analysis_results = {}
analysis_status = {}
deepseek_results = {}
deepseek_status = {}

class VideoAnalyzerWeb:
    def __init__(self):
        self.analyzer = VideoAnalyzer()

    def analyze_video_async(self, task_id, video_url, text_prompt):
        """异步分析视频（URL方式）"""
        try:
            analysis_status[task_id] = {"status": "downloading", "progress": 20}

            # 下载视频
            temp_path = self.analyzer.download_video_from_url(video_url)

            analysis_status[task_id] = {"status": "encoding", "progress": 40}

            analysis_status[task_id] = {"status": "analyzing", "progress": 60}

            # 使用流式响应进行完整分析，不限制token数量
            result = self.analyzer.analyze_video_from_url(
                video_url=video_url,
                text_prompt=text_prompt,
                max_tokens=None,  # 不限制token数量
                stream=False  # Web应用暂时使用非流式以便获取完整结果
            )

            analysis_status[task_id] = {"status": "completed", "progress": 100}
            analysis_results[task_id] = {
                "success": True,
                "result": result,
                "video_url": video_url,
                "prompt": text_prompt,
                "type": "url"
            }

            # 清理临时文件
            try:
                os.unlink(temp_path)
            except:
                pass

        except Exception as e:
            analysis_status[task_id] = {"status": "error", "progress": 0}
            analysis_results[task_id] = {
                "success": False,
                "error": str(e),
                "video_url": video_url,
                "prompt": text_prompt,
                "type": "url"
            }

    def analyze_uploaded_video_async(self, task_id, video_path, text_prompt, original_filename):
        """异步分析上传的视频文件"""
        try:
            analysis_status[task_id] = {"status": "processing", "progress": 30}

            # 直接使用上传的文件进行分析
            analysis_status[task_id] = {"status": "encoding", "progress": 50}
            analysis_status[task_id] = {"status": "analyzing", "progress": 70}

            # 使用本地视频分析方法
            result = self.analyzer.analyze_video_local(
                video_path=video_path,
                text_prompt=text_prompt,
                max_tokens=None,  # 不限制token数量
                stream=False  # Web应用暂时使用非流式以便获取完整结果
            )

            analysis_status[task_id] = {"status": "completed", "progress": 100}
            analysis_results[task_id] = {
                "success": True,
                "result": result,
                "video_url": original_filename,
                "prompt": text_prompt,
                "type": "upload"
            }

            # 清理上传的文件
            try:
                os.unlink(video_path)
            except:
                pass

        except Exception as e:
            analysis_status[task_id] = {"status": "error", "progress": 0}
            analysis_results[task_id] = {
                "success": False,
                "error": str(e),
                "video_url": original_filename,
                "prompt": text_prompt,
                "type": "upload"
            }

  def analyze_direct(self, text_prompt, model="gemini-2.5-flash", max_tokens=None, stream=False):
        """
        直接分析文本内容，不处理视频
        用于第三步的人物分析，基于已有的DeepSeek结果进行AI分析

        Args:
            text_prompt: 分析要求的文字描述
            model: 使用的模型名称
            max_tokens: 最大token数（None表示无限制）
            stream: 是否使用流式响应

        Returns:
            AI分析结果
        """
        return self.analyzer.analyze_direct(text_prompt, model, max_tokens, stream)

# 初始化Web分析器
web_analyzer = VideoAnalyzerWeb()
deepseek_processor = DeepSeekProcessor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    video_url = data.get('video_url', '').strip()
    text_prompt = data.get('text_prompt', '').strip()

    if not video_url:
        return jsonify({"success": False, "error": "请输入视频URL"})

    if not text_prompt:
        text_prompt = "请详细描述这个视频的内容"

    # 生成任务ID
    task_id = str(int(time.time() * 1000))

    # 启动异步分析
    thread = threading.Thread(
        target=web_analyzer.analyze_video_async,
        args=(task_id, video_url, text_prompt)
    )
    thread.start()

    return jsonify({"success": True, "task_id": task_id})

@app.route('/analyze/batch', methods=['POST'])
def analyze_batch():
    """批量人物分析接口，用于第三步"""
    data = request.json
    text_prompt = data.get('text_prompt', '').strip()
    batch_id = data.get('batch_id', '').strip()

    if not text_prompt:
        text_prompt = "请详细描述这个视频的内容"

    if not batch_id:
        return jsonify({"success": False, "error": "未提供批次ID"})

    # 生成任务ID
    task_id = str(int(time.time() * 1000))

    try:
        # 直接调用AI分析，不进行视频下载
        # 因为第三步是基于第二步的结果进行分析，不需要重新处理视频
        result = web_analyzer.analyze_direct(
            text_prompt=text_prompt,
            model="claude-3-5-sonnet-20241022"
        )

        analysis_results[task_id] = {
            "success": True,
            "result": result,
            "type": "batch_person_analysis"
        }

        return jsonify({
            "success": True,
            "task_id": task_id,
            "result": result  # 直接返回结果，因为是同步处理
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/upload', methods=['POST'])
def upload_video():
    """处理单个视频文件上传（保持兼容性）"""
    return upload_videos_single()

@app.route('/upload/batch', methods=['POST'])
def upload_videos():
    """处理批量视频文件上传"""
    try:
        # 检查是否有文件被上传
        if 'video_files' not in request.files:
            return jsonify({"success": False, "error": "没有选择文件"})

        files = request.files.getlist('video_files')
        text_prompt = request.form.get('text_prompt', '').strip()

        if not files or files[0].filename == '':
            return jsonify({"success": False, "error": "没有选择文件"})

        # 验证文件数量
        if len(files) > 10:
            return jsonify({"success": False, "error": "最多只能同时上传10个视频文件"})

        if len(files) == 0:
            return jsonify({"success": False, "error": "请至少选择一个视频文件"})

        # 处理每个文件
        uploaded_files = []
        total_size = 0

        for file in files:
            # 检查文件名
            if file.filename == '':
                continue

            # 检查文件类型
            if not allowed_file(file.filename):
                return jsonify({
                    "success": False,
                    "error": f"文件 '{file.filename}' 格式不支持。支持的格式: {', '.join(ALLOWED_EXTENSIONS)}"
                })

            # 检查文件大小
            if hasattr(file, 'content_length'):
                file_size = file.content_length
            else:
                file.seek(0, 2)  # 移动到文件末尾
                file_size = file.tell()
                file.seek(0)  # 重置到文件开头

            if file_size > 100 * 1024 * 1024:  # 100MB
                return jsonify({
                    "success": False,
                    "error": f"文件 '{file.filename}' 大小超过100MB限制"
                })

            total_size += file_size

        # 检查总大小限制（可选）
        if total_size > 500 * 1024 * 1024:  # 500MB 总限制
            return jsonify({"success": False, "error": "所有文件总大小超过500MB限制"})

        if not text_prompt:
            text_prompt = "请详细描述这个视频的内容"

        # 生成批次ID
        batch_id = str(int(time.time() * 1000))

        # 为每个文件生成独立任务
        tasks = []
        for file in files:
            if file.filename == '':
                continue

            # 保存文件
            filename = secure_filename(file.filename)
            timestamp = str(int(time.time() * 1000 * (hash(filename) % 1000)))
            saved_filename = f"{timestamp}_{filename}"
            video_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)

            file.save(video_path)

            # 生成任务ID
            task_id = f"{batch_id}_{len(tasks)}"

            # 启动异步分析
            thread = threading.Thread(
                target=web_analyzer.analyze_uploaded_video_async,
                args=(task_id, video_path, text_prompt, filename)
            )
            thread.start()

            tasks.append({
                "task_id": task_id,
                "filename": filename,
                "original_name": file.filename
            })

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "tasks": tasks,
            "total_files": len(tasks)
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"批量上传失败: {str(e)}"})

def upload_videos_single():
    """处理单个视频文件上传"""
    try:
        # 检查是否有文件被上传
        if 'video_file' not in request.files:
            return jsonify({"success": False, "error": "没有选择文件"})

        file = request.files['video_file']
        text_prompt = request.form.get('text_prompt', '').strip()

        # 检查文件名是否为空
        if file.filename == '':
            return jsonify({"success": False, "error": "没有选择文件"})

        # 检查文件类型
        if not allowed_file(file.filename):
            return jsonify({
                "success": False,
                "error": f"不支持的文件格式。支持的格式: {', '.join(ALLOWED_EXTENSIONS)}"
            })

        # 保存上传的文件
        filename = secure_filename(file.filename)
        timestamp = str(int(time.time() * 1000))
        saved_filename = f"{timestamp}_{filename}"
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)

        file.save(video_path)

        # 检查文件大小（额外验证）
        file_size = os.path.getsize(video_path)
        if file_size > 100 * 1024 * 1024:  # 100MB
            os.unlink(video_path)
            return jsonify({"success": False, "error": "文件大小超过100MB限制"})

        if not text_prompt:
            text_prompt = "请详细描述这个视频的内容"

        # 生成任务ID
        task_id = str(int(time.time() * 1000))

        # 启动异步分析
        thread = threading.Thread(
            target=web_analyzer.analyze_uploaded_video_async,
            args=(task_id, video_path, text_prompt, filename)
        )
        thread.start()

        return jsonify({"success": True, "task_id": task_id})

    except Exception as e:
        return jsonify({"success": False, "error": f"上传失败: {str(e)}"})

@app.route('/batch/status/<batch_id>')
def get_batch_status(batch_id):
    """获取批次状态"""
    try:
        # 获取所有相关任务的状态
        batch_tasks = {}
        completed_count = 0
        error_count = 0

        for task_id, status in analysis_status.items():
            if batch_id in task_id:  # 检查是否属于该批次
                task_result = analysis_results.get(task_id, {})
                batch_tasks[task_id] = {
                    "status": status.get("status", "unknown"),
                    "progress": status.get("progress", 0),
                    "filename": task_result.get("video_url", "未知文件"),
                    "success": task_result.get("success", False),
                    "error": task_result.get("error") if not task_result.get("success", False) else None
                }

                if status.get("status") == "completed":
                    completed_count += 1
                elif status.get("status") == "error":
                    error_count += 1

        total_tasks = len(batch_tasks)
        overall_progress = 0
        if total_tasks > 0:
            overall_progress = int((completed_count + error_count) / total_tasks * 100)

        overall_status = "processing"
        if completed_count + error_count == total_tasks:
            overall_status = "completed" if error_count == 0 else "completed_with_errors"

        return jsonify({
            "batch_id": batch_id,
            "overall_status": overall_status,
            "overall_progress": overall_progress,
            "total_tasks": total_tasks,
            "completed_count": completed_count,
            "error_count": error_count,
            "tasks": batch_tasks
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"获取批次状态失败: {str(e)}"})

@app.route('/batch/results/<batch_id>')
def get_batch_results(batch_id):
    """获取批次结果"""
    try:
        batch_results = {}

        for task_id, result in analysis_results.items():
            if batch_id in task_id:  # 检查是否属于该批次
                batch_results[task_id] = {
                    "filename": result.get("video_url", "未知文件"),
                    "success": result.get("success", False),
                    "result": result.get("result") if result.get("success", False) else None,
                    "error": result.get("error") if not result.get("success", False) else None
                }

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "results": batch_results,
            "total_count": len(batch_results)
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"获取批次结果失败: {str(e)}"})

@app.route('/status/<task_id>')
def get_status(task_id):
    status = analysis_status.get(task_id, {"status": "not_found", "progress": 0})
    return jsonify(status)

@app.route('/result/<task_id>')
def get_result(task_id):
    result = analysis_results.get(task_id)
    if result:
        return jsonify(result)
    else:
        return jsonify({"success": False, "error": "结果未找到"})

# DeepSeek处理端点
@app.route('/deepseek/process', methods=['POST'])
def deepseek_process():
    """单个视频分析结果的DeepSeek处理"""
    try:
        data = request.json
        video_result = data.get('video_result', '').strip()
        user_prompt = data.get('user_prompt', '').strip()

        if not video_result:
            return jsonify({"success": False, "error": "视频分析结果不能为空"})

        # 生成任务ID
        task_id = str(int(time.time() * 1000))

        # 设置状态
        deepseek_status[task_id] = {"status": "processing", "progress": 50}

        try:
            # 调用DeepSeek处理
            result = deepseek_processor.process_video_analysis_result(
                video_analysis_text=video_result,
                user_prompt=user_prompt,
                model="deepseek-chat",
                stream=False
            )

            # 保存结果
            deepseek_status[task_id] = {"status": "completed", "progress": 100}
            deepseek_results[task_id] = {
                "success": True,
                "result": result,
                "video_result": video_result,
                "prompt": user_prompt,
                "type": "single"
            }

            return jsonify({
                "success": True,
                "task_id": task_id,
                "result": result
            })

        except Exception as e:
            deepseek_status[task_id] = {"status": "error", "progress": 0}
            deepseek_results[task_id] = {
                "success": False,
                "error": str(e),
                "video_result": video_result,
                "prompt": user_prompt,
                "type": "single"
            }
            return jsonify({"success": False, "error": f"DeepSeek处理失败: {str(e)}"})

    except Exception as e:
        return jsonify({"success": False, "error": f"请求处理失败: {str(e)}"})

@app.route('/deepseek/process/batch', methods=['POST'])
def deepseek_process_batch():
    """批量视频分析结果的DeepSeek处理"""
    try:
        data = request.json
        video_results = data.get('video_results', [])
        user_prompt = data.get('user_prompt', '').strip()

        if not video_results:
            return jsonify({"success": False, "error": "视频分析结果列表不能为空"})

        # 生成批次ID
        batch_id = str(int(time.time() * 1000))

        # 处理每个视频结果
        batch_results = []

        for i, video_result in enumerate(video_results):
            try:
                task_id = f"{batch_id}_{i}"
                deepseek_status[task_id] = {"status": "processing", "progress": 50}

                # 调用DeepSeek处理
                result = deepseek_processor.process_video_analysis_result(
                    video_analysis_text=video_result,
                    user_prompt=user_prompt,
                    model="deepseek-chat",
                    stream=False
                )

                deepseek_status[task_id] = {"status": "completed", "progress": 100}
                deepseek_results[task_id] = {
                    "success": True,
                    "result": result,
                    "video_result": video_result,
                    "prompt": user_prompt,
                    "type": "batch",
                    "batch_id": batch_id,
                    "video_index": i
                }

                batch_results.append({
                    "video_index": i,
                    "success": True,
                    "result": result
                })

            except Exception as e:
                task_id = f"{batch_id}_{i}"
                deepseek_status[task_id] = {"status": "error", "progress": 0}
                deepseek_results[task_id] = {
                    "success": False,
                    "error": str(e),
                    "video_result": video_result,
                    "prompt": user_prompt,
                    "type": "batch",
                    "batch_id": batch_id,
                    "video_index": i
                }

                batch_results.append({
                    "video_index": i,
                    "success": False,
                    "error": str(e)
                })

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "results": batch_results,
            "total_count": len(batch_results)
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"批量处理失败: {str(e)}"})

@app.route('/deepseek/status/<task_id>')
def get_deepseek_status(task_id):
    """获取DeepSeek处理状态"""
    status = deepseek_status.get(task_id, {"status": "not_found", "progress": 0})
    return jsonify(status)

@app.route('/deepseek/result/<task_id>')
def get_deepseek_result(task_id):
    """获取DeepSeek处理结果"""
    result = deepseek_results.get(task_id)
    if result:
        return jsonify(result)
    else:
        return jsonify({"success": False, "error": "DeepSeek结果未找到"})

@app.route('/deepseek/batch/result/<batch_id>')
def get_deepseek_batch_result(batch_id):
    """获取批量DeepSeek处理结果"""
    try:
        batch_results = {}

        for task_id, result in deepseek_results.items():
            if batch_id in task_id:  # 检查是否属于该批次
                video_index = result.get("video_index", 0)
                batch_results[video_index] = {
                    "success": result.get("success", False),
                    "result": result.get("result") if result.get("success", False) else None,
                    "error": result.get("error") if not result.get("success", False) else None
                }

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "results": batch_results,
            "total_count": len(batch_results)
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"获取批量DeepSeek结果失败: {str(e)}"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "Video Analyzer API"})

if __name__ == '__main__':
    # 创建templates目录
    if not os.path.exists('templates'):
        os.makedirs('templates')

    # 创建static目录
    if not os.path.exists('static'):
        os.makedirs('static')

    print("🚀 视频分析Web服务启动中...")
    print("📱 请在浏览器中访问: http://localhost:5001")
    print("⚠️  确保你的API密钥已正确配置")

    app.run(host='0.0.0.0', port=5001, debug=True)