from flask import Flask, render_template, request, jsonify, Response
from flask import stream_with_context
import os
import re
import uuid
import shutil
import subprocess
from video_analyzer import VideoAnalyzer
from deepseek_processor import DeepSeekProcessor
import threading
import time
import base64
from werkzeug.utils import secure_filename
import requests
import io
import zipfile

app = Flask(__name__)

# 配置文件上传
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
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
edl_tasks = {}
original_name_map = {}
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')

@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get('Origin') or '*'
    resp.headers['Access-Control-Allow-Origin'] = origin
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp

class VideoAnalyzerWeb:
    def __init__(self):
        self.analyzer = VideoAnalyzer()

    def analyze_video_async(self, task_id, video_url, text_prompt, model):
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
                model=model,
                max_tokens=None,  # 不限制token数量
                stream=False  # Web应用暂时使用非流式以便获取完整结果
            )

            analysis_status[task_id] = {"status": "completed", "progress": 100}
            analysis_results[task_id] = {
                "success": True,
                "result": result,
                "video_url": video_url,
                "prompt": text_prompt,
                "model": model,
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
                "model": model,
                "type": "url"
            }

    def analyze_uploaded_video_async(self, task_id, video_path, text_prompt, original_filename, model):
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
                model=model,
                max_tokens=None,  # 不限制token数量
                stream=False  # Web应用暂时使用非流式以便获取完整结果
            )

            analysis_status[task_id] = {"status": "completed", "progress": 100}
            analysis_results[task_id] = {
                "success": True,
                "result": result,
                "video_url": original_filename,
                "prompt": text_prompt,
                "model": model,
                "type": "upload"
            }


        except Exception as e:
            analysis_status[task_id] = {"status": "error", "progress": 0}
            analysis_results[task_id] = {
                "success": False,
                "error": str(e),
                "video_url": original_filename,
                "prompt": text_prompt,
                "model": model,
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
    model = (data.get('model') or '').strip()
    if model not in {"gemini-2.5-flash", "gemini-2.5-pro"}:
        model = "gemini-2.5-flash"

    if not video_url:
        return jsonify({"success": False, "error": "请输入视频URL"})

    if not text_prompt:
        text_prompt = "请详细描述这个视频的内容"

    # 生成任务ID
    task_id = str(int(time.time() * 1000))

    # 启动异步分析
    thread = threading.Thread(
        target=web_analyzer.analyze_video_async,
        args=(task_id, video_url, text_prompt, model)
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
        model = (request.form.get('model') or '').strip()
        if model not in {"gemini-2.5-flash", "gemini-2.5-pro"}:
            model = "gemini-2.5-flash"

        if not files or files[0].filename == '':
            return jsonify({"success": False, "error": "没有选择文件"})

        # 验证文件数量
        if len(files) > 100:
            return jsonify({"success": False, "error": "最多只能同时上传100个视频文件"})

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

        # 检查总大小限制
        if total_size > 10 * 1024 * 1024 * 1024:  # 10GB 总限制
            return jsonify({"success": False, "error": "所有文件总大小超过10GB限制"})

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
            original_name_map.setdefault(file.filename, []).append(saved_filename)
            if secure_filename(file.filename) != file.filename:
                original_name_map.setdefault(secure_filename(file.filename), []).append(saved_filename)

            # 生成任务ID
            task_id = f"{batch_id}_{len(tasks)}"

            # 启动异步分析
            thread = threading.Thread(
                target=web_analyzer.analyze_uploaded_video_async,
                args=(task_id, video_path, text_prompt, file.filename, model)
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
        model = (request.form.get('model') or '').strip()
        if model not in {"gemini-2.5-flash", "gemini-2.5-pro"}:
            model = "gemini-2.5-flash"

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
        original_name_map.setdefault(file.filename, []).append(saved_filename)
        if secure_filename(file.filename) != file.filename:
            original_name_map.setdefault(secure_filename(file.filename), []).append(saved_filename)

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
            args=(task_id, video_path, text_prompt, file.filename, model)
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

@app.route('/json-merge/process', methods=['POST'])
def json_merge_process():
    """第四步JSON拼接处理接口"""
    try:
        data = request.json
        text_prompt = data.get('text_prompt', '').strip()
        batch_id = data.get('batch_id', '').strip()

        if not text_prompt:
            return jsonify({"success": False, "error": "文本提示词不能为空"})

        # 生成任务ID
        task_id = str(int(time.time() * 1000))

        # 设置状态
        deepseek_status[task_id] = {"status": "processing", "progress": 50}

        try:
            # 直接调用DeepSeek处理
            result = deepseek_processor.process_video_analysis_result(
                video_analysis_text=text_prompt,  # 这里传入完整的拼接文本
                user_prompt="",  # 不需要额外的用户提示词
                model="deepseek-chat",
                stream=False
            )

            # 保存结果
            deepseek_status[task_id] = {"status": "completed", "progress": 100}
            deepseek_results[task_id] = {
                "success": True,
                "result": result,
                "prompt": text_prompt,
                "type": "json_merge",
                "batch_id": batch_id
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
                "prompt": text_prompt,
                "type": "json_merge",
                "batch_id": batch_id
            }
            return jsonify({"success": False, "error": f"JSON拼接处理失败: {str(e)}"})

    except Exception as e:
        return jsonify({"success": False, "error": f"请求处理失败: {str(e)}"})

@app.route('/script/generate', methods=['POST'])
def script_generate():
    try:
        data = request.json
        script_prompt = data.get('script_prompt', '').strip()
        batch_id = data.get('batch_id', '').strip()
        source_type = (data.get('source_type', 'json_merge') or 'json_merge').strip()
        model_provider = (data.get('model_provider', 'deepseek') or 'deepseek').strip()
        if source_type not in ('json_merge', 'script_generate'):
            source_type = 'json_merge'

        if not script_prompt:
            return jsonify({"success": False, "error": "脚本提示词不能为空"})

        if not batch_id:
            return jsonify({"success": False, "error": "未提供批次ID"})

        merged_texts = []
        for task_id, result in deepseek_results.items():
            if result.get("type") == source_type and result.get("success", False):
                if result.get("batch_id") == batch_id:
                    merged_texts.append(result.get("result", ""))

        if not merged_texts:
            if source_type == 'json_merge':
                return jsonify({"success": False, "error": "未找到第4步的JSON拼接结果"})
            else:
                return jsonify({"success": False, "error": "未找到第5步的脚本生成结果"})

        combined_input = "\n\n".join([t for t in merged_texts if t])
        def _preview_text(label, text):
            try:
                sample = text[:300]
                is_ascii = all(ord(ch) < 128 for ch in sample)
                print(f"[script_generate] {label}_preview(len={len(text)} ascii={is_ascii}) -> {sample}")
            except Exception as _e:
                print(f"[script_generate] {label}_preview error={str(_e)}")
        print(f"[script_generate] batch_id={batch_id} source_type={source_type} provider={model_provider} prompt_len={len(script_prompt)} combined_len={len(combined_input)}")
        _preview_text('script_prompt', script_prompt)
        _preview_text('combined_input', combined_input)

        task_id = str(int(time.time() * 1000))
        deepseek_status[task_id] = {"status": "processing", "progress": 50}

        try:
            if model_provider == 'glm-4-long':
                print(f"[script_generate] task_id={task_id} call glm-4-long")
                api_key = os.environ.get('BIGMODEL_API_KEY', '').strip()
                if not api_key:
                    raise Exception('缺少GLM-4-Long API密钥')
                full_input = f"{script_prompt}\n\n{combined_input}"
                url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json; charset=utf-8',
                    'Accept-Charset': 'utf-8'
                }
                payload = {
                    'model': 'glm-4-long',
                    'messages': [
                        {'role': 'user', 'content': full_input}
                    ]
                }
                print(f"[script_generate] task_id={task_id} glm payload messages_len={len(payload['messages'])} content_len={len(full_input)}")
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                print(f"[script_generate] task_id={task_id} glm status_code={resp.status_code}")
                if resp.status_code != 200:
                    body_preview = resp.text[:500]
                    raise Exception(f"GLM-4-Long调用失败: HTTP {resp.status_code} body={body_preview}")
                data_json = resp.json()
                result = ''
                try:
                    choices = data_json.get('choices') or []
                    if choices:
                        msg = choices[0].get('message') or {}
                        result = msg.get('content') or ''
                except:
                    pass
                if not result:
                    result = str(data_json)
                print(f"[script_generate] task_id={task_id} glm result_len={len(result)}")
            elif model_provider and model_provider != 'deepseek':
                print(f"[script_generate] task_id={task_id} call laozhang model={model_provider}")
                api_key = os.environ.get('LAOZHANG_API_KEY', '').strip()
                if not api_key:
                    raise Exception('缺少LaoZhang API密钥')
                full_input = f"{script_prompt}\n\n{combined_input}"
                url = 'https://api.laozhang.ai/v1/chat/completions'
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json; charset=utf-8',
                    'Accept-Charset': 'utf-8'
                }
                payload = {
                    'model': model_provider,
                    'messages': [
                        {'role': 'user', 'content': full_input}
                    ]
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                print(f"[script_generate] task_id={task_id} laozhang status_code={resp.status_code}")
                if resp.status_code != 200:
                    body_preview = ''
                    try:
                        body_preview = resp.text[:500]
                    except:
                        pass
                    raise Exception(f"LaoZhang调用失败: HTTP {resp.status_code} body={body_preview}")
                data_json = resp.json()
                result = ''
                try:
                    choices = data_json.get('choices') or []
                    if choices:
                        msg = choices[0].get('message') or {}
                        result = msg.get('content') or ''
                except:
                    pass
                if not result:
                    result = str(data_json)
            else:
                print(f"[script_generate] task_id={task_id} call deepseek")
                result = deepseek_processor.process_video_analysis_result(
                    video_analysis_text=combined_input,
                    user_prompt=script_prompt,
                    model="deepseek-chat",
                    stream=False
                )
                print(f"[script_generate] task_id={task_id} deepseek result_len={len(str(result))}")

            deepseek_status[task_id] = {"status": "completed", "progress": 100}
            deepseek_results[task_id] = {
                "success": True,
                "result": result,
                "prompt": script_prompt,
                "type": ("script_generate" if source_type == 'json_merge' else "script_extract"),
                "batch_id": batch_id
            }

            return jsonify({
                "success": True,
                "task_id": task_id,
                "result": result
            })

        except Exception as e:
            deepseek_status[task_id] = {"status": "error", "progress": 0}
            print(f"[script_generate] task_id={task_id} error={str(e)}")
            deepseek_results[task_id] = {
                "success": False,
                "error": str(e),
                "prompt": script_prompt,
                "type": ("script_generate" if source_type == 'json_merge' else "script_extract"),
                "batch_id": batch_id
            }
            return jsonify({"success": False, "error": f"脚本生成失败: {str(e)}"})

    except Exception as e:
        return jsonify({"success": False, "error": f"请求处理失败: {str(e)}"})

@app.route('/script/generate_direct', methods=['POST'])
def script_generate_direct():
    try:
        data = request.json or {}
        script_prompt = (data.get('script_prompt') or '').strip()
        model_provider = (data.get('model_provider') or 'deepseek').strip()
        json_texts = data.get('json_texts') or []
        if not script_prompt:
            return jsonify({"success": False, "error": "脚本提示词不能为空"})
        if not isinstance(json_texts, list) or not json_texts:
            return jsonify({"success": False, "error": "未提供JSON内容"})
        combined_input = "\n\n".join([str(t) for t in json_texts if t])
        def _preview_text(label, text):
            try:
                sample = text[:300]
                is_ascii = all(ord(ch) < 128 for ch in sample)
                print(f"[script_generate_direct] {label}_preview(len={len(text)} ascii={is_ascii}) -> {sample}")
            except Exception as _e:
                print(f"[script_generate_direct] {label}_preview error={str(_e)}")
        print(f"[script_generate_direct] provider={model_provider} prompt_len={len(script_prompt)} combined_len={len(combined_input)}")
        _preview_text('script_prompt', script_prompt)
        _preview_text('combined_input', combined_input)
        task_id = str(int(time.time() * 1000))
        deepseek_status[task_id] = {"status": "processing", "progress": 50}
        try:
            if model_provider == 'glm-4-long':
                api_key = os.environ.get('BIGMODEL_API_KEY', '').strip()
                if not api_key:
                    raise Exception('缺少GLM-4-Long API密钥')
                full_input = f"{script_prompt}\n\n{combined_input}"
                url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json; charset=utf-8',
                    'Accept-Charset': 'utf-8'
                }
                payload = {
                    'model': 'glm-4-long',
                    'messages': [
                        {'role': 'user', 'content': full_input}
                    ]
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code != 200:
                    body_preview = resp.text[:500]
                    raise Exception(f"GLM-4-Long调用失败: HTTP {resp.status_code} body={body_preview}")
                data_json = resp.json()
                result = ''
                try:
                    choices = data_json.get('choices') or []
                    if choices:
                        msg = choices[0].get('message') or {}
                        result = msg.get('content') or ''
                except:
                    pass
                if not result:
                    result = str(data_json)
            elif model_provider and model_provider != 'deepseek':
                api_key = os.environ.get('LAOZHANG_API_KEY', '').strip()
                if not api_key:
                    raise Exception('缺少LaoZhang API密钥')
                full_input = f"{script_prompt}\n\n{combined_input}"
                url = 'https://api.laozhang.ai/v1/chat/completions'
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json; charset=utf-8',
                    'Accept-Charset': 'utf-8'
                }
                payload = {
                    'model': model_provider,
                    'messages': [
                        {'role': 'user', 'content': full_input}
                    ]
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                if resp.status_code != 200:
                    body_preview = ''
                    try:
                        body_preview = resp.text[:500]
                    except:
                        pass
                    raise Exception(f"LaoZhang调用失败: HTTP {resp.status_code} body={body_preview}")
                data_json = resp.json()
                result = ''
                try:
                    choices = data_json.get('choices') or []
                    if choices:
                        msg = choices[0].get('message') or {}
                        result = msg.get('content') or ''
                except:
                    pass
                if not result:
                    result = str(data_json)
            else:
                result = deepseek_processor.process_video_analysis_result(
                    video_analysis_text=combined_input,
                    user_prompt=script_prompt,
                    model="deepseek-chat",
                    stream=False
                )
            deepseek_status[task_id] = {"status": "completed", "progress": 100}
            deepseek_results[task_id] = {
                "success": True,
                "result": result,
                "prompt": script_prompt,
                "type": "script_direct",
                "batch_id": ""
            }
            return jsonify({"success": True, "task_id": task_id, "result": result})
        except Exception as e:
            deepseek_status[task_id] = {"status": "error", "progress": 0}
            deepseek_results[task_id] = {
                "success": False,
                "error": str(e),
                "prompt": script_prompt,
                "type": "script_direct",
                "batch_id": ""
            }
            return jsonify({"success": False, "error": f"脚本生成失败: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": f"请求处理失败: {str(e)}"})

@app.route('/edl/upload/batch', methods=['POST', 'OPTIONS'])
def edl_upload_batch():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        if 'edl_files' not in request.files:
            return jsonify({'success': False, 'error': '没有选择文件'})
        files = request.files.getlist('edl_files')
        if not files or files[0].filename == '':
            return jsonify({'success': False, 'error': '没有选择文件'})
        if len(files) > 300:
            return jsonify({'success': False, 'error': '最多同时上传300个文件'})
        saved = []
        total_size = 0
        for f in files:
            if f.filename == '':
                continue
            if not allowed_file(f.filename):
                return jsonify({'success': False, 'error': f"文件 '{f.filename}' 格式不支持"})
            if hasattr(f, 'content_length'):
                sz = f.content_length
            else:
                f.seek(0, 2)
                sz = f.tell()
                f.seek(0)
            if sz > 100 * 1024 * 1024:
                return jsonify({'success': False, 'error': f"文件 '{f.filename}' 大小超过100MB限制"})
            total_size += sz
        if total_size > 10 * 1024 * 1024 * 1024:
            return jsonify({'success': False, 'error': '所有文件总大小超过10GB限制'})
        for f in files:
            if f.filename == '':
                continue
            fn = secure_filename(f.filename)
            ts = str(int(time.time() * 1000))
            saved_fn = f"{ts}_{fn}"
            p = os.path.join(app.config['UPLOAD_FOLDER'], saved_fn)
            f.save(p)
            original_name_map.setdefault(f.filename, []).append(saved_fn)
            if secure_filename(f.filename) != f.filename:
                original_name_map.setdefault(secure_filename(f.filename), []).append(saved_fn)
            saved.append({'original': f.filename, 'saved': saved_fn})
        return jsonify({'success': True, 'files': saved})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def mmssff_to_hhmmss_ms(ts, fps):
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", ts)
    if not m:
        return None
    mm = int(m.group(1))
    ss = int(m.group(2))
    ff = int(m.group(3))
    total_ms = int(((mm * 60) + ss) * 1000 + (ff * 1000) / max(1, fps))
    hh = total_ms // 3600000
    rem = total_ms % 3600000
    m2 = rem // 60000
    rem2 = rem % 60000
    s2 = rem2 // 1000
    ms = rem2 % 1000
    return f"{hh:02d}:{m2:02d}:{s2:02d}.{ms:03d}"

def mmssff_to_frame_index(ts, fps):
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", ts)
    if not m:
        return None
    mm = int(m.group(1))
    ss = int(m.group(2))
    ff = int(m.group(3))
    return mm * 60 * max(1, fps) + ss * max(1, fps) + ff

def resolve_source_file(name, allowed=None):
    base = os.path.basename(name).strip()
    sbase = secure_filename(base)
    patterns = {base, sbase}
    if base.lower().endswith('.mp4.txt'):
        patterns.add(base[:-4])
        patterns.add(sbase[:-4])
    if '.' not in base:
        for ext in ['.mp4', '.MP4', '.mov', '.MOV', '.mkv', '.MKV']:
            patterns.add(base + ext)
            patterns.add(sbase + ext)
    allowed_set = None
    if isinstance(allowed, list) and allowed:
        try:
            allowed_set = set([os.path.basename(str(a)).strip() for a in allowed if a])
        except Exception:
            allowed_set = None
    try:
        for fname in os.listdir(app.config['UPLOAD_FOLDER']):
            if (fname in patterns) or any(fname.endswith(p) for p in patterns):
                if allowed_set and fname not in allowed_set:
                    continue
                p = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                if os.path.exists(p):
                    return p
    except Exception:
        pass
    mapped = original_name_map.get(base) or original_name_map.get(sbase)
    if mapped:
        if isinstance(mapped, list):
            for fn in mapped:
                bfn = os.path.basename(fn)
                if allowed_set and bfn not in allowed_set:
                    continue
                p = os.path.join(app.config['UPLOAD_FOLDER'], fn)
                if os.path.exists(p):
                    return p
        else:
            bfn = os.path.basename(mapped)
            if not allowed_set or bfn in allowed_set:
                p = os.path.join(app.config['UPLOAD_FOLDER'], mapped)
                if os.path.exists(p):
                    return p
    return None

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def ffmpeg_available():
    return shutil.which('ffmpeg') is not None

def run_ffmpeg_segment(src, start, duration, out_path):
    cmd = ['ffmpeg', '-hide_banner', '-y', '-ss', start, '-t', str(duration), '-i', src, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', out_path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0:
        return True, p.stderr.decode('utf-8', errors='ignore')
    cmd_vo = ['ffmpeg', '-hide_banner', '-y', '-ss', start, '-t', str(duration), '-i', src, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-an', out_path]
    p2 = subprocess.run(cmd_vo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log = (p.stderr.decode('utf-8', errors='ignore') or '') + '\n' + (p2.stderr.decode('utf-8', errors='ignore') or '')
    return p2.returncode == 0, log

def run_ffmpeg_segment_frames(src, start_frame, end_frame, fps, out_path):
    start_sec = start_frame / max(1, fps)
    end_sec = end_frame / max(1, fps)
    filter_complex = f"[0:v]trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS[v];[0:a]atrim=start={start_sec}:end={end_sec},asetpts=PTS-STARTPTS[a]"
    cmd = ['ffmpeg', '-hide_banner', '-y', '-i', src, '-filter_complex', filter_complex, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', out_path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0:
        return True, p.stderr.decode('utf-8', errors='ignore')
    filter_complex_vo = f"[0:v]trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS[v]"
    cmd_vo = ['ffmpeg', '-hide_banner', '-y', '-i', src, '-filter_complex', filter_complex_vo, '-map', '[v]', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', out_path]
    p2 = subprocess.run(cmd_vo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log = (p.stderr.decode('utf-8', errors='ignore') or '') + '\n' + (p2.stderr.decode('utf-8', errors='ignore') or '')
    return p2.returncode == 0, log

def run_ffmpeg_concat(list_path, out_path):
    cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path, '-c:v', 'libx264', '-c:a', 'aac', out_path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0:
        return True, p.stderr.decode('utf-8', errors='ignore')
    cmd_vo = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path, '-c:v', 'libx264', '-an', out_path]
    p2 = subprocess.run(cmd_vo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log = (p.stderr.decode('utf-8', errors='ignore') or '') + '\n' + (p2.stderr.decode('utf-8', errors='ignore') or '')
    return p2.returncode == 0, log

def ffprobe_resolution(path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', path]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode('utf-8', errors='ignore').strip()
        if 'x' in out:
            parts = out.split('x')
            w = int(parts[0])
            h = int(parts[1])
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return None, None

def run_ffmpeg_concat_filter(seg_dir, total, out_path):
    inputs = [os.path.join(seg_dir, f"seg_{i:03d}.mp4") for i in range(1, total+1)]
    w, h = ffprobe_resolution(inputs[0]) if inputs else (None, None)
    if not w or not h:
        w, h = 1280, 720
    filter_parts = []
    for i in range(total):
        filter_parts.append(f"[{i}:v]scale={w}:{h}[v{i}]")
    concat_inputs = ''.join([f"[v{i}]" for i in range(total)])
    filter_parts.append(f"{concat_inputs}concat=n={total}:v=1:a=0[outv]")
    filter = ';'.join(filter_parts)
    cmd = ['ffmpeg', '-hide_banner', '-y']
    for inp in inputs:
        cmd += ['-i', inp]
    cmd += ['-filter_complex', filter, '-map', '[outv]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', out_path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode == 0, p.stderr.decode('utf-8', errors='ignore')

def edit_video_task(task_id, clips, fps, mode, allowed=None):
    edl_tasks[task_id] = {'progress': 0, 'status': '初始化', 'done': False, 'logs': []}
    edl_tasks[task_id]['logs'].append(f"task={task_id} start total_clips={len(clips)} fps={fps}")
    try:
        edl_tasks[task_id]['logs'].append(f"clips_payload={clips}")
    except Exception:
        pass
    if not ffmpeg_available():
        edl_tasks[task_id] = {'progress': 0, 'status': '错误', 'error': '缺少ffmpeg，请安装后重试', 'done': True, 'logs': edl_tasks[task_id]['logs']}
        edl_tasks[task_id]['logs'].append("ffmpeg not found")
        return
    seg_dir = os.path.join('temp', 'segments', task_id)
    ensure_dir(seg_dir)
    ensure_dir(os.path.join('outputs', 'edits'))
    total = len(clips)
    for i, clip in enumerate(clips, start=1):
        edl_tasks[task_id]['status'] = f"处理片段 {i}/{total}"
        edl_tasks[task_id]['current_index'] = i
        req_name = clip.get('source_file','')
        src = resolve_source_file(req_name, allowed)
        if not src:
            try:
                base = os.path.basename((req_name or '').strip())
                sbase = secure_filename(base)
                edl_tasks[task_id]['logs'].append(f"resolve_source failed name={base} sbase={sbase}")
                mapped_base = original_name_map.get(base)
                mapped_sbase = original_name_map.get(sbase)
                edl_tasks[task_id]['logs'].append(f"original_name_map[base]={mapped_base}")
                edl_tasks[task_id]['logs'].append(f"original_name_map[sbase]={mapped_sbase}")
                try:
                    endswith_matches = [fn for fn in os.listdir(app.config['UPLOAD_FOLDER']) if sbase and fn.endswith(sbase)]
                except Exception:
                    endswith_matches = []
                edl_tasks[task_id]['logs'].append(f"uploads_endswith_sbase={endswith_matches}")
                try:
                    dir_list = sorted(os.listdir(app.config['UPLOAD_FOLDER']))
                    edl_tasks[task_id]['logs'].append(f"uploads_list_sample={dir_list[:20]}")
                except Exception:
                    pass
            except Exception:
                pass
            edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"找不到源文件: {req_name}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
            return
        ts = clip.get('start_ts','')
        dur = float(clip.get('duration_sec',0))
        out_seg = os.path.join(seg_dir, f"seg_{i:03d}.mp4")
        if (mode or 'time') == 'frames':
            sf = mmssff_to_frame_index(ts, fps)
            if sf is None or dur <= 0:
                edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"非法帧值: {ts}/{dur}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
                edl_tasks[task_id]['logs'].append(f"invalid frames ts={ts} dur={dur}")
                return
            ef = sf + int(round(dur * max(1, fps)))
            edl_tasks[task_id]['logs'].append(f"clip {i}/{total} src={src} start_frame={sf} end_frame={ef} fps={fps} out={out_seg}")
            ok, log = run_ffmpeg_segment_frames(src, sf, ef, fps, out_seg)
        else:
            hhmmss = mmssff_to_hhmmss_ms(ts, fps)
            if not hhmmss or dur <= 0:
                edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"非法时间值: {ts}/{dur}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
                edl_tasks[task_id]['logs'].append(f"invalid ts/dur ts={ts} dur={dur}")
                return
            edl_tasks[task_id]['logs'].append(f"clip {i}/{total} src={src} start={hhmmss} dur={dur} out={out_seg}")
            ok, log = run_ffmpeg_segment(src, hhmmss, dur, out_seg)
        if not ok:
            edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"片段生成失败: {log[:400]}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
            edl_tasks[task_id]['logs'].append(f"ffmpeg segment error: {log[:200]}")
            return
        edl_tasks[task_id]['logs'].append(f"segment ok {out_seg}")
        edl_tasks[task_id]['progress'] = int((i/total)*100)
    list_path = os.path.join(seg_dir, 'list.txt')
    with open(list_path, 'w') as f:
        for i in range(1, total+1):
            f.write(f"file 'seg_{i:03d}.mp4'\n")
    edl_tasks[task_id]['logs'].append(f"concat list {list_path}")
    out_path = os.path.join('outputs', 'edits', f"{task_id}.mp4")
    ok, log = run_ffmpeg_concat(list_path, out_path)
    if not ok:
        edl_tasks[task_id]['logs'].append(f"ffmpeg concat error: {log[:200]}")
        ok2, log2 = run_ffmpeg_concat_filter(seg_dir, total, out_path)
        if not ok2:
            combined = (log or '') + '\n' + (log2 or '')
            edl_tasks[task_id] = {'progress': 100, 'status': '错误', 'error': f"拼接失败: {combined[:400]}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
            edl_tasks[task_id]['logs'].append(f"ffmpeg concat filter error: {log2[:200]}")
            return
    edl_tasks[task_id] = {'progress': 100, 'status': '完成', 'output_path': out_path, 'done': True, 'logs': edl_tasks[task_id]['logs']}
    edl_tasks[task_id]['logs'].append(f"output {out_path}")

@app.route('/video/edl/start', methods=['POST', 'OPTIONS'])
def video_edl_start():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        data = request.get_json(silent=True) or {}
        fps = int(data.get('fps', 30))
        mode = (data.get('mode') or 'time').strip()
        if mode not in ('time','frames'):
            mode = 'time'
        clips = data.get('clips') or []
        allowed = data.get('allowed_files') or None
        if not clips:
            return jsonify({'success': False, 'error': '剪辑清单为空'}), 400
        tid = str(uuid.uuid4()).replace('-', '')
        t = threading.Thread(target=edit_video_task, args=(tid, clips, fps, mode, allowed), daemon=True)
        t.start()
        return jsonify({'success': True, 'task_id': tid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/video/edl/resolve', methods=['POST', 'OPTIONS'])
def video_edl_resolve():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        allowed = data.get('allowed') or None
        if not name:
            return jsonify({'success': False, 'error': '缺少name'}), 400
        p = resolve_source_file(name, allowed)
        if p:
            return jsonify({'success': True, 'path': p})
        return jsonify({'success': False, 'error': '未找到'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/video/edl/status/<task_id>', methods=['GET', 'OPTIONS'])
def video_edl_status(task_id):
    if request.method == 'OPTIONS':
        return Response(status=200)
    s = edl_tasks.get(task_id)
    if not s:
        return jsonify({'success': False, 'error': '任务不存在'})
    logs = s.get('logs') or []
    if len(logs) > 200:
        logs = logs[-200:]
    resp = dict(s)
    resp['logs'] = logs
    return jsonify(resp)

@app.route('/uploads/list', methods=['GET'])
def list_uploads():
    try:
        files = []
        for fname in os.listdir(app.config['UPLOAD_FOLDER']):
            p = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            if os.path.isfile(p):
                files.append(fname)
        files.sort()
        return jsonify({'success': True, 'files': files})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "Video Analyzer API"})

# 新增：下载txt文件
@app.route('/download/txt', methods=['POST'])
def download_txt():
    try:
        data = request.json or {}
        filename = (data.get('filename') or '').strip()
        content = data.get('content') or ''
        if not filename:
            filename = 'result.txt'
        filename = filename.split('/')[-1].split('\\')[-1]
        if not filename.lower().endswith('.txt'):
            filename = f"{filename}.txt"
        return Response(
            content,
            mimetype='text/plain; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"下载失败: {str(e)}"}), 500

# 新增：打包批量结果为zip
@app.route('/download/zip', methods=['POST'])
def download_zip():
    try:
        data = request.json or {}
        files = data.get('files') or []
        if not isinstance(files, list) or not files:
            return jsonify({"success": False, "error": "缺少文件列表"}), 400
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for item in files:
                name = (item.get('filename') or 'result').strip()
                text = item.get('content') or ''
                name = name.split('/')[-1].split('\\')[-1]
                if not name.lower().endswith('.txt'):
                    name = f"{name}.txt"
                zf.writestr(name, text)
        zip_buf.seek(0)
        zip_name = (data.get('zip_name') or 'results.zip').strip()
        if not zip_name.lower().endswith('.zip'):
            zip_name = f"{zip_name}.zip"
        return Response(
            zip_buf.read(),
            mimetype='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{zip_name}"'
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"压缩失败: {str(e)}"}), 500

@app.route('/voiceover/generate', methods=['POST'])
def voiceover_generate():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        voice_id = (data.get('voice_id') or 'JNyLRc3LFmQDImliF0sT').strip()
        model_id = (data.get('model_id') or 'eleven_multilingual_v2').strip()
        output_format = (data.get('output_format') or 'mp3_44100_128').strip()
        batch_id = (data.get('batch_id') or f"voiceover_{int(time.time()*1000)}").strip()
        index = int(data.get('index') or 0)
        if not text:
            return jsonify({"success": False, "error": "台词文本不能为空"}), 400

        api_key = ELEVENLABS_API_KEY or (os.getenv('XI_API_KEY') or os.getenv('ELEVEN_LABS_API_KEY') or os.getenv('XI_API_KEY') or '')
        explicit_key = (data.get('api_key') or '').strip()
        if explicit_key:
            api_key = explicit_key
        if not api_key:
            api_key = 'sk_a987b9d1c1b709ef8c5bb1fbb0dfa8b35eeea98b89c35775'

        base_url = 'https://api.elevenlabs.io/v1'
        url = f"{base_url}/text-to-speech/{voice_id}/stream?output_format={output_format}"
        headers = {
            'Accept': 'audio/mpeg',
            'Content-Type': 'application/json',
            'xi-api-key': api_key
        }
        payload = {
            'text': text,
            'model_id': model_id
        }

        out_dir = os.path.join('static', 'voiceover', batch_id)
        ensure_dir(out_dir)
        out_path = os.path.join(out_dir, f"seg_{index:03d}.mp3")

        r = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
        if r.status_code != 200:
            try:
                err_json = r.json()
                return jsonify({"success": False, "error": err_json.get('detail') or err_json.get('error') or f"TTS接口错误: {r.status_code}"}), 500
            except Exception:
                return jsonify({"success": False, "error": f"TTS接口错误: {r.status_code}"}), 500

        with open(out_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        rel_url = f"/static/voiceover/{batch_id}/seg_{index:03d}.mp3"
        return jsonify({"success": True, "url": rel_url, "file_path": out_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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