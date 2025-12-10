from flask import Flask, render_template, request, jsonify, Response, send_file
from flask import g
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
import logging
from datetime import datetime
import json
import concurrent.futures

def _load_env_files():
    paths = [".env.local", ".env"]
    for p in paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith("#"):
                            continue
                        k, sep, v = s.partition("=")
                        if sep:
                            key = k.strip()
                            val = v.strip()
                            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                val = val[1:-1]
                            if key and val and key not in os.environ:
                                os.environ[key] = val
        except Exception:
            pass

_load_env_files()

app = Flask(__name__)

# 配置日志
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_handlers = []
try:
    _log_dir = os.getenv('LOG_DIR', '/tmp')
    os.makedirs(_log_dir, exist_ok=True)
    _handlers.append(logging.FileHandler(os.path.join(_log_dir, 'app.log'), encoding='utf-8'))
except Exception:
    pass
_handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO, format=log_format, handlers=_handlers)

# 创建专用日志器
logger = logging.getLogger(__name__)
packaging_logger = logging.getLogger('video_packaging')
episode_logger = logging.getLogger('episode_narration')

# 配置文件上传
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024

def ensure_writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        fallback = os.path.join('/tmp', path.replace('\\', '/').strip('/'))
        os.makedirs(fallback, exist_ok=True)
        return fallback

app.config['UPLOAD_FOLDER'] = ensure_writable_dir(os.getenv('UPLOAD_FOLDER', 'uploads'))

# 确保上传目录存在
ensure_writable_dir(app.config['UPLOAD_FOLDER'])

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {
    'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv',  # 视频
    'mp3', 'wav', 'aac', 'm4a', 'ogg', 'flac',          # 音频
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'  # 图片
}

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
episode_results = {}
episode_status = {}
_voices_cache = {}
_models_cache = {}
_cache_ttl_sec = 600

def _episode_analyze_one(batch_id, index, filename, save_path, user_prompt, model):
    try:
        try:
            items = episode_status.get(batch_id, {}).get('items')
            if items and 0 <= index < len(items):
                items[index]['status'] = 'processing'
        except Exception:
            pass
        t0 = time.time()
        analyzer = VideoAnalyzer()
        result_text = analyzer.analyze_video_local(save_path, user_prompt, model=model, max_tokens=None, stream=False)
        t1 = time.time()
        duration_ms = int((t1 - t0) * 1000)
        res = {'index': index, 'filename': filename, 'success': True, 'result': result_text, 'model': model, 'duration_ms': duration_ms}
        try:
            if isinstance(episode_results.get(batch_id), list) and 0 <= index < len(episode_results[batch_id]):
                episode_results[batch_id][index] = res
            else:
                episode_results.setdefault(batch_id, []).append(res)
            st = episode_status.get(batch_id, {})
            if st:
                st['count'] = st.get('count', 0) + 1
                items = st.get('items')
                if items and 0 <= index < len(items):
                    items[index]['status'] = 'done'
                    items[index]['duration_ms'] = duration_ms
                    items[index]['model'] = model
        except Exception:
            pass
        return res
    except Exception as e:
        try:
            st = episode_status.get(batch_id, {})
            items = st.get('items') if st else None
            if items and 0 <= index < len(items):
                items[index]['status'] = 'failed'
        except Exception:
            pass
        raise e

@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get('Origin') or '*'
    resp.headers['Access-Control-Allow-Origin'] = origin
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    req_headers = request.headers.get('Access-Control-Request-Headers')
    if req_headers:
        resp.headers['Access-Control-Allow-Headers'] = req_headers
    else:
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, apikey'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
    resp.headers['Access-Control-Max-Age'] = '86400'
    resp.headers['Vary'] = 'Origin, Access-Control-Request-Headers, Access-Control-Request-Method'
    return resp

@app.route('/api/files/<path:subpath>')
def serve_stored_file(subpath):
    base = app.config.get('UPLOAD_FOLDER') or 'uploads'
    p = os.path.abspath(os.path.join(base, subpath))
    base_abs = os.path.abspath(base)
    if not p.startswith(base_abs) or not os.path.exists(p):
        return jsonify({'success': False, 'error': 'File not found'}), 404
    return send_file(p)

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

@app.route('/favicon.ico')
def favicon():
    return Response(status=204)

@app.route('/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/analyze/batch', methods=['POST', 'OPTIONS'])
def analyze_batch():
    """批量人物分析接口，用于第三步"""
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/upload', methods=['POST', 'OPTIONS'])
def upload_video():
    """处理单个视频文件上传（保持兼容性）"""
    if request.method == 'OPTIONS':
        return Response(status=200)
    return upload_videos_single()

@app.route('/upload/batch', methods=['POST', 'OPTIONS'])
def upload_videos():
    """处理批量视频文件上传"""
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
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

@app.route('/upload/url', methods=['POST', 'OPTIONS'])
def upload_videos_by_url():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        data = request.get_json(silent=True) or {}
        urls = data.get('video_urls') or []
        text_prompt = (data.get('text_prompt') or '').strip()
        model = (data.get('model') or '').strip()
        if model not in {"gemini-2.5-flash", "gemini-2.5-pro"}:
            model = "gemini-2.5-flash"
        if not isinstance(urls, list) or not urls:
            return jsonify({"success": False, "error": "video_urls 不能为空"}), 400
        if not text_prompt:
            text_prompt = "请详细描述这个视频的内容"
        batch_id = str(int(time.time() * 1000))
        tasks = []
        for i, video_url in enumerate(urls):
            task_id = f"{batch_id}_{i}"
            thread = threading.Thread(
                target=web_analyzer.analyze_video_async,
                args=(task_id, video_url, text_prompt, model)
            )
            thread.start()
            tasks.append({"task_id": task_id, "video_url": video_url})
        return jsonify({"success": True, "batch_id": batch_id, "tasks": tasks, "total_files": len(tasks)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
@app.route('/deepseek/process', methods=['POST', 'OPTIONS'])
def deepseek_process():
    """单个视频分析结果的DeepSeek处理"""
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/deepseek/process/batch', methods=['POST', 'OPTIONS'])
def deepseek_process_batch():
    """批量视频分析结果的DeepSeek处理"""
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/json-merge/process', methods=['POST', 'OPTIONS'])
def json_merge_process():
    """第四步JSON拼接处理接口"""
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/script/generate', methods=['POST', 'OPTIONS'])
def script_generate():
    if request.method == 'OPTIONS':
        return Response(status=200)
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
        alt_step5_texts = []
        if source_type != 'script_generate':
            for task_id, result in deepseek_results.items():
                if result.get("type") in ("script_generate", "script_extract") and result.get("success", False):
                    if result.get("batch_id") == batch_id:
                        alt_step5_texts.append(result.get("result", ""))
            if alt_step5_texts:
                merged_texts = alt_step5_texts

        if not merged_texts:
            if source_type == 'json_merge':
                return jsonify({"success": False, "error": "未找到第4步的JSON拼接结果"})
            else:
                return jsonify({"success": False, "error": "未找到第5步的脚本生成结果"})

        def _extract_script_narration(raw):
            try:
                if isinstance(raw, dict):
                    if 'Script (Narration)' in raw:
                        v = raw.get('Script (Narration)')
                        return str(v or '').strip()
                    for k in ('Script', 'Narration', 'script', 'narration'):
                        if k in raw:
                            v = raw.get(k)
                            return str(v or '').strip()
                    return ''
                s = str(raw or '').strip()
                if s.startswith('```'):
                    s = re.sub(r'^```[a-zA-Z]*\n?', '', s)
                    s = re.sub(r'\n?```$', '', s)
                try:
                    obj = json.loads(s)
                    return _extract_script_narration(obj)
                except Exception:
                    pass
                m = re.search(r'Script\s*\(Narration\)\s*[:：]\s*(.+)', s, re.IGNORECASE | re.DOTALL)
                if m:
                    val = m.group(1)
                    nxt = re.search(r'\n[A-Za-z][^\n]{0,50}[:：]', val)
                    if nxt:
                        val = val[:nxt.start()]
                    return str(val or '').strip()
            except Exception:
                return ''
            return ''

        if source_type == 'script_generate' or alt_step5_texts:
            narrations = []
            for t in merged_texts:
                n = _extract_script_narration(t)
                if n:
                    narrations.append(n)
            combined_input = "\n\n".join(narrations)
        else:
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
                print(f"[script_generate] task_id={task_id} env LAOZHANG_API_KEY present={bool(api_key)}")
                if not api_key:
                    try:
                        env_status = {k: bool(os.environ.get(k)) for k in ['LAOZHANG_API_KEY', 'BIGMODEL_API_KEY']}
                        print(f"[script_generate] task_id={task_id} env keys status: {env_status}")
                    except Exception as _e:
                        print(f"[script_generate] task_id={task_id} env status check error={str(_e)}")
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

@app.route('/script/generate_direct', methods=['POST', 'OPTIONS'])
def script_generate_direct():
    if request.method == 'OPTIONS':
        return Response(status=200)
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
                print(f"[script_generate_direct] env LAOZHANG_API_KEY present={bool(api_key)}")
                if not api_key:
                    try:
                        env_status = {k: bool(os.environ.get(k)) for k in ['LAOZHANG_API_KEY', 'BIGMODEL_API_KEY']}
                        print(f"[script_generate_direct] env keys status: {env_status}")
                    except Exception as _e:
                        print(f"[script_generate_direct] env status check error={str(_e)}")
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
            saved_fn = fn
            p = os.path.join(app.config['UPLOAD_FOLDER'], saved_fn)
            f.save(p)
            saved.append({'original': f.filename, 'saved': saved_fn})
        return jsonify({'success': True, 'files': saved})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Episode Narration logging hooks
@app.before_request
def _episode_before_request():
    try:
        path = request.path or ''
        if path.startswith('/episode/narration'):
            g.__episode_start__ = time.time()
            meta = {
                'method': request.method,
                'path': path,
                'args': dict(request.args or {}),
                'content_type': request.headers.get('Content-Type', ''),
                'content_length': request.headers.get('Content-Length')
            }
            episode_logger.info(f"EPISODE_REQ_START {json.dumps(meta, ensure_ascii=False)}")
    except Exception:
        pass

@app.after_request
def _episode_after_request(resp):
    try:
        path = request.path or ''
        if path.startswith('/episode/narration'):
            t0 = getattr(g, '__episode_start__', None)
            dur_ms = int((time.time() - t0) * 1000) if t0 else None
            meta = {
                'method': request.method,
                'path': path,
                'status': resp.status_code,
                'duration_ms': dur_ms,
                'resp_type': resp.headers.get('Content-Type', '')
            }
            episode_logger.info(f"EPISODE_REQ_DONE {json.dumps(meta, ensure_ascii=False)}")
    except Exception:
        pass
    return resp

@app.teardown_request
def _episode_teardown_request(err):
    try:
        if err is not None:
            path = request.path or ''
            if path.startswith('/episode/narration'):
                episode_logger.error(f"EPISODE_REQ_ERR {str(err)}")
    except Exception:
        pass

@app.route('/episode/narration/tts', methods=['POST'])
def episode_narration_tts():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        voice_id = (data.get('voice_id') or '21m00Tcm4TlvDq8ikWAM').strip()
        model_id = (data.get('model_id') or 'eleven_multilingual_v2').strip()
        batch_id = str(data.get('batch_id') or 'default').strip()
        index = int(data.get('index') or 0)
        row = int(data.get('row') or 0)
        api_key = ELEVENLABS_API_KEY or (os.getenv('XI_API_KEY') or os.getenv('ELEVEN_LABS_API_KEY') or '')
        explicit_key = (data.get('api_key') or '').strip()
        if explicit_key:
            api_key = explicit_key
        if not api_key:
            return jsonify({'success': False, 'error': '缺少ELEVENLABS_API_KEY'})
        if not text:
            return jsonify({'success': False, 'error': '文本为空'})
        out_dir = ensure_writable_dir(os.path.join(app.config['UPLOAD_FOLDER'], 'voiceover', f'episode_tts_{batch_id}_{index}'))
        out_path = os.path.join(out_dir, f'line_{row:03d}.mp3')
        url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream'
        payload = {
            'text': text,
            'model_id': model_id,
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75
            }
        }
        headers = {
            'xi-api-key': api_key,
            'accept': 'audio/mpeg',
            'Content-Type': 'application/json'
        }
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code >= 400:
            try:
                err_txt = r.text[:500]
            except Exception:
                err_txt = str(r.status_code)
            return jsonify({'success': False, 'error': f'ElevenLabs错误: {err_txt}'})
        try:
            with open(out_path, 'wb') as f:
                f.write(r.content)
        except Exception as e:
            return jsonify({'success': False, 'error': f'保存失败: {str(e)}'})
        rel = out_path.replace('\\', '/')
        base = app.config.get('UPLOAD_FOLDER') or 'uploads'
        rel_subpath = os.path.relpath(rel, base).replace('\\', '/')
        return jsonify({'success': True, 'file': rel, 'url': f"/api/files/{rel_subpath}"})
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
    if not base:
        return None
    allowed_set = None
    allowed_saved = set()
    allowed_sbase = set()
    if isinstance(allowed, list) and allowed:
        try:
            allowed_set = set([os.path.basename(str(a)).strip() for a in allowed if a])
        except Exception:
            allowed_set = None
        try:
            for a in (allowed_set or []):
                sa = secure_filename(a)
                if sa:
                    allowed_sbase.add(sa)
                mapped = original_name_map.get(a) or original_name_map.get(sa) or []
                for saved in mapped:
                    fname = os.path.basename(str(saved).strip())
                    if fname:
                        allowed_saved.add(fname)
        except Exception:
            pass
    try:
        for fname in os.listdir(app.config['UPLOAD_FOLDER']):
            if fname == base:
                if allowed_set and (fname not in allowed_set and fname not in allowed_saved):
                    continue
                p = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                if os.path.exists(p):
                    return p
    except Exception:
        return None
    sbase = secure_filename(base)
    try:
        mapped = original_name_map.get(base) or original_name_map.get(sbase) or []
        for saved in mapped:
            fname = os.path.basename(str(saved).strip())
            if not fname:
                continue
            if allowed_set and (fname not in allowed_set and fname not in allowed_saved):
                continue
            p = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            if os.path.exists(p):
                return p
    except Exception:
        pass
    try:
        candidates = []
        for fname in os.listdir(app.config['UPLOAD_FOLDER']):
            if sbase and (fname.endswith(sbase) or any(fname.endswith(sa) for sa in allowed_sbase)):
                candidates.append(fname)
        if candidates:
            candidates.sort()
            p = os.path.join(app.config['UPLOAD_FOLDER'], candidates[-1])
            if os.path.exists(p):
                return p
    except Exception:
        pass
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

def run_ffmpeg_concat(list_path, out_path, original_volume=100):
    # 确保音量参数在有效范围内
    original_volume = max(0, min(100, int(original_volume or 100)))
    print(f"[DEBUG] run_ffmpeg_concat called with original_volume={original_volume}%")

    # 如果音量是100%，使用原始命令
    if original_volume == 100:
        cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path, '-c:v', 'libx264', '-c:a', 'aac', out_path]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0:
            return True, p.stderr.decode('utf-8', errors='ignore')
        # 备用：无音频版本
        cmd_vo = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path, '-c:v', 'libx264', '-an', out_path]
        p2 = subprocess.run(cmd_vo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log = (p.stderr.decode('utf-8', errors='ignore') or '') + '\n' + (p2.stderr.decode('utf-8', errors='ignore') or '')
        return p2.returncode == 0, log

    # 如果音量不是100%，应用音量滤镜
    if original_volume == 0:
        # 音量为0，只输出视频无音频
        cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path, '-c:v', 'libx264', '-an', out_path]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log = p.stderr.decode('utf-8', errors='ignore')
        return p.returncode == 0, log
    else:
        # 应用音量滤镜
        volume_factor = original_volume / 100.0
        print(f"[DEBUG] Applying volume filter with factor={volume_factor}")
        cmd = ['ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,
               '-filter_complex', f'[0:a]volume={volume_factor}[a]',
               '-map', '0:v', '-map', '[a]',
               '-c:v', 'libx264', '-c:a', 'aac', out_path]
        print(f"[DEBUG] FFmpeg volume command: {' '.join(cmd)}")
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"[DEBUG] FFmpeg volume command return code: {p.returncode}")
        if p.returncode == 0:
            print(f"[DEBUG] Volume filter succeeded")
            return True, p.stderr.decode('utf-8', errors='ignore')
        else:
            print(f"[DEBUG] Volume filter failed, stderr: {p.stderr.decode('utf-8', errors='ignore')}")
        # 备用：无音频版本
        print(f"[DEBUG] Falling back to video-only version")
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

def edit_video_task(task_id, clips, fps, mode, allowed=None, original_volume=100):
    edl_tasks[task_id] = {'progress': 0, 'status': '初始化', 'done': False, 'logs': []}
    edl_tasks[task_id]['logs'].append(f"task={task_id} start total_clips={len(clips)} fps={fps} original_volume={original_volume}%")
    print(f"[DEBUG] EDL_TASK_START: task_id={task_id}, total_clips={len(clips)}, fps={fps}, original_volume={original_volume}%")

    # 计算预期总时长
    total_expected_duration = sum(clip.get('duration_sec', 0) for clip in clips)
    print(f"[DEBUG] EXPECTED_TOTAL_DURATION: {total_expected_duration}s")
    try:
        edl_tasks[task_id]['logs'].append(f"clips_payload={clips}")
    except Exception:
        pass
    if not ffmpeg_available():
        edl_tasks[task_id] = {'progress': 0, 'status': '错误', 'error': '缺少ffmpeg，请安装后重试', 'done': True, 'logs': edl_tasks[task_id]['logs']}
        edl_tasks[task_id]['logs'].append("ffmpeg not found")
        return
    seg_dir = ensure_writable_dir(os.path.join('temp', 'segments', task_id))
    out_base = ensure_writable_dir(os.path.join('outputs', 'edits'))
    total = len(clips)
    for i, clip in enumerate(clips, start=1):
        edl_tasks[task_id]['status'] = f"处理片段 {i}/{total}"
        edl_tasks[task_id]['current_index'] = i
        req_name = clip.get('source_file','')

        # 详细调试每个片段信息
        clip_duration = float(clip.get('duration_sec', 0))
        clip_start_ts = clip.get('start_ts', '')
        print(f"[DEBUG CLIP {i}]: source_file={req_name}, duration_sec={clip_duration}, start_ts={clip_start_ts}")
        print(f"[DEBUG CLIP {i}]: clip_data={clip}")

        src = resolve_source_file(req_name, allowed)
        print(f"[DEBUG RESOLVE {i}]: resolved_source={src}")

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

        print(f"[DEBUG FFMPEG {i}]: ts={ts}, dur={dur}, out_seg={out_seg}")

        if (mode or 'time') == 'frames':
            sf = mmssff_to_frame_index(ts, fps)
            if sf is None or dur <= 0:
                print(f"[DEBUG ERROR {i}]: Invalid frames ts={ts} dur={dur}")
                edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"非法帧值: {ts}/{dur}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
                edl_tasks[task_id]['logs'].append(f"invalid frames ts={ts} dur={dur}")
                return
            ef = sf + int(round(dur * max(1, fps)))
            print(f"[DEBUG FFMPEG {i}]: FRAMES mode - sf={sf}, ef={ef}, fps={fps}")
            edl_tasks[task_id]['logs'].append(f"clip {i}/{total} src={src} start_frame={sf} end_frame={ef} fps={fps} out={out_seg}")
            ok, log = run_ffmpeg_segment_frames(src, sf, ef, fps, out_seg)
        else:
            hhmmss = mmssff_to_hhmmss_ms(ts, fps)
            if not hhmmss or dur <= 0:
                print(f"[DEBUG ERROR {i}]: Invalid time ts={ts} dur={dur} hhmmss={hhmmss}")
                edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"非法时间值: {ts}/{dur}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
                edl_tasks[task_id]['logs'].append(f"invalid ts/dur ts={ts} dur={dur}")
                return
            print(f"[DEBUG FFMPEG {i}]: TIME mode - hhmmss={hhmmss}, dur={dur}")
            edl_tasks[task_id]['logs'].append(f"clip {i}/{total} src={src} start={hhmmss} dur={dur} out={out_seg}")
            ok, log = run_ffmpeg_segment(src, hhmmss, dur, out_seg)

        print(f"[DEBUG RESULT {i}]: FFmpeg segment ok={ok}, log={log[:100] if log else 'None'}")

        if not ok:
            print(f"[DEBUG ERROR {i}]: FFmpeg segment failed: {log[:200] if log else 'Unknown error'}")
            edl_tasks[task_id] = {'progress': int((i-1)/total*100), 'status': '错误', 'error': f"片段生成失败: {log[:400]}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
            edl_tasks[task_id]['logs'].append(f"ffmpeg segment error: {log[:200]}")
            return

        # 验证生成的片段文件
        if os.path.exists(out_seg):
            file_size = os.path.getsize(out_seg)
            print(f"[DEBUG VERIFIED {i}]: Segment file exists, size={file_size} bytes")
            # 尝试获取实际视频时长
            try:
                import subprocess
                result = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', out_seg],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    actual_duration = float(result.stdout.strip())
                    print(f"[DEBUG DURATION {i}]: Expected={dur}s, Actual={actual_duration}s, Diff={actual_duration - dur}s")
                else:
                    print(f"[DEBUG DURATION {i}]: Failed to get duration - ffprobe error")
            except Exception as e:
                print(f"[DEBUG DURATION {i}]: Exception getting duration - {e}")
        else:
            print(f"[DEBUG ERROR {i}]: Segment file was not created: {out_seg}")

        edl_tasks[task_id]['logs'].append(f"segment ok {out_seg}")
        edl_tasks[task_id]['progress'] = int((i/total)*100)
    # 计算所有片段的总预期时长
    total_expected_duration = sum(float(clip.get('duration_sec', 0)) for clip in clips)
    print(f"[DEBUG CONCAT SUMMARY]: Expected total duration={total_expected_duration}s from {total} segments")

    list_path = os.path.join(seg_dir, 'list.txt')
    with open(list_path, 'w') as f:
        for i in range(1, total+1):
            abs_seg = os.path.abspath(os.path.join(seg_dir, f"seg_{i:03d}.mp4"))
            f.write(f"file '{abs_seg}'\n")
            # 验证每个片段文件在拼接列表中存在
            if os.path.exists(abs_seg):
                size = os.path.getsize(abs_seg)
                print(f"[DEBUG CONCAT LIST {i}]: {abs_seg} exists, size={size}")
            else:
                print(f"[DEBUG CONCAT ERROR {i}]: {abs_seg} does not exist!")

    print(f"[DEBUG CONCAT]: Created list file {list_path}")
    edl_tasks[task_id]['logs'].append(f"concat list {list_path}")

    out_path = os.path.join(out_base, f"{task_id}.mp4")
    print(f"[DEBUG CONCAT]: Starting concatenation to {out_path}")

    ok, log = run_ffmpeg_concat(list_path, out_path, original_volume)
    print(f"[DEBUG CONCAT RESULT]: Primary concat ok={ok}, log={log[:100] if log else 'None'}")

    # 如果拼接成功，验证最终输出文件的时长
    if ok and os.path.exists(out_path):
        try:
            import subprocess
            result = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', out_path],
                                  capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                final_duration = float(result.stdout.strip())
                duration_diff = final_duration - total_expected_duration
                print(f"[DEBUG FINAL DURATION]: Expected={total_expected_duration}s, Actual={final_duration}s, Difference={duration_diff}s")
                if abs(duration_diff) > 0.1:  # 如果差异超过0.1秒
                    print(f"[WARNING]: Duration mismatch detected! Missing {abs(duration_diff)} seconds")
            else:
                print(f"[DEBUG FINAL DURATION]: Failed to get final duration - ffprobe error: {result.stderr}")
        except Exception as e:
            print(f"[DEBUG FINAL DURATION]: Exception getting final duration - {e}")

    if not ok:
        print(f"[DEBUG CONCAT]: Primary concat failed, trying fallback method")
        edl_tasks[task_id]['logs'].append(f"ffmpeg concat error: {log[:200]}")
        ok2, log2 = run_ffmpeg_concat_filter(seg_dir, total, out_path)
        print(f"[DEBUG CONCAT FALLBACK RESULT]: ok={ok2}, log={log2[:100] if log2 else 'None'}")
        if not ok2:
            combined = (log or '') + '\n' + (log2 or '')
            edl_tasks[task_id] = {'progress': 100, 'status': '错误', 'error': f"拼接失败: {combined[:400]}", 'done': True, 'logs': edl_tasks[task_id]['logs']}
            edl_tasks[task_id]['logs'].append(f"ffmpeg concat filter error: {log2[:200]}")
            return

    print(f"[DEBUG CONCAT]: Concatenation completed successfully")
    edl_tasks[task_id] = {'progress': 100, 'status': '完成', 'output_path': out_path, 'done': True, 'logs': edl_tasks[task_id]['logs']}
    edl_tasks[task_id]['logs'].append(f"output {out_path}")

@app.route('/video/edl/start', methods=['POST', 'OPTIONS'])
def video_edl_start():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        data = request.get_json(silent=True) or {}
        print(f"[DEBUG] /video/edl/start received data: {data}")
        fps = int(data.get('fps', 30))
        mode = (data.get('mode') or 'time').strip()
        if mode not in ('time','frames'):
            mode = 'time'
        clips = data.get('clips') or []
        allowed = data.get('allowed_files') or None
        original_volume = data.get('original_volume', 100)
        # 确保音量参数在有效范围内
        try:
            original_volume = max(0, min(100, int(original_volume)))
        except (ValueError, TypeError):
            original_volume = 100
        print(f"[DEBUG] Processed: fps={fps}, mode={mode}, clips_count={len(clips)}, original_volume={original_volume}")
        if not clips:
            return jsonify({'success': False, 'error': '剪辑清单为空'}), 400
        tid = str(uuid.uuid4()).replace('-', '')
        t = threading.Thread(target=edit_video_task, args=(tid, clips, fps, mode, allowed, original_volume), daemon=True)
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
        try:
            print(f"[edl_resolve] name={name} allowed_len={(len(allowed) if isinstance(allowed, list) else 0)}")
        except Exception:
            pass
        p = resolve_source_file(name, allowed)
        if p:
            try:
                print(f"[edl_resolve] found path={p}")
            except Exception:
                pass
            return jsonify({'success': True, 'path': p})
        try:
            print(f"[edl_resolve] not_found name={name}")
        except Exception:
            pass
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

@app.route('/auth/status', methods=['GET', 'OPTIONS'])
def auth_status():
    if request.method == 'OPTIONS':
        return Response(status=200)
    a = getattr(g, '__auth__', {}) or {}
    return jsonify({
        'authenticated': bool(a.get('valid')),
        'user': a.get('user')
    })

# 新增：下载txt文件
@app.route('/download/txt', methods=['POST', 'OPTIONS'])
def download_txt():
    if request.method == 'OPTIONS':
        return Response(status=200)
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
@app.route('/download/zip', methods=['POST', 'OPTIONS'])
def download_zip():
    if request.method == 'OPTIONS':
        return Response(status=200)
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

@app.route('/voiceover/generate', methods=['POST', 'OPTIONS'])
def voiceover_generate():
    if request.method == 'OPTIONS':
        return Response(status=200)
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

        out_dir = ensure_writable_dir(os.path.join(app.config['UPLOAD_FOLDER'], 'voiceover', batch_id))
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

        base = app.config.get('UPLOAD_FOLDER') or 'uploads'
        rel_subpath = os.path.relpath(out_path, base).replace('\\', '/')
        rel_url = f"/api/files/{rel_subpath}"
        return jsonify({"success": True, "url": rel_url, "file_path": out_path, "voice_id": voice_id, "model_id": model_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/elevenlabs/voices', methods=['GET'])
def elevenlabs_voices():
    try:
        api_key = ELEVENLABS_API_KEY or (os.getenv('XI_API_KEY') or os.getenv('ELEVEN_LABS_API_KEY') or os.getenv('XI_API_KEY') or '')
        explicit = (request.args.get('api_key') or '').strip()
        print(f"[elevenlabs_voices] explicit_provided={bool(explicit)} env_present={bool(api_key)}")
        if explicit:
            api_key = explicit
        if not api_key:
            print("[elevenlabs_voices] missing api key")
            return jsonify({"success": False, "error": "缺少ElevenLabs API密钥"}), 400
        base_url = 'https://api.elevenlabs.io'
        url = f"{base_url}/v2/voices"
        base_params = {}
        q = (request.args.get('search') or '').strip()
        if q:
            base_params['search'] = q
        req_ps = request.args.get('page_size')
        ps = 100
        if req_ps:
            try:
                ps = min(int(req_ps), 100)
            except Exception:
                ps = 100
        cache_key = f"k={bool(api_key)}|q={q}|ps={ps}"
        now = time.time()
        try:
            cached = _voices_cache.get(cache_key)
            if cached and (now - cached['ts'] < _cache_ttl_sec):
                print(f"[elevenlabs_voices] cache_hit key={cache_key}")
                return jsonify({"success": True, "voices": cached['data']})
        except Exception:
            pass
        headers = { 'xi-api-key': api_key }
        voices = []
        next_token = None
        has_more = True
        loops = 0
        while has_more and loops < 50:
            loops += 1
            params = dict(base_params)
            params['page_size'] = ps
            if next_token:
                params['next_page_token'] = next_token
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[elevenlabs_voices] page_status={resp.status_code} loops={loops}")
            if resp.status_code != 200:
                body_preview = ''
                try:
                    body_preview = resp.text[:300]
                except Exception:
                    pass
                print(f"[elevenlabs_voices] error_body={body_preview}")
                break
            data = resp.json()
            items = data.get('voices') or data.get('items') or []
            for v in items:
                vid = (v.get('voice_id') or v.get('id') or '').strip()
                name = (v.get('name') or '').strip()
                if vid and name:
                    voices.append({ 'id': vid, 'name': name })
            has_more = bool(data.get('has_more'))
            next_token = data.get('next_page_token')
            if not has_more or not next_token:
                break
        # Deduplicate by id
        try:
            seen = set()
            deduped = []
            for v in voices:
                if v['id'] in seen:
                    continue
                seen.add(v['id'])
                deduped.append(v)
            voices = deduped
        except Exception:
            pass
        print(f"[elevenlabs_voices] voices_total={len(voices)} loops={loops}")
        try:
            _voices_cache[cache_key] = { 'ts': now, 'data': voices }
        except Exception:
            pass
        if not voices:
            cached = _voices_cache.get(cache_key)
            if cached:
                print(f"[elevenlabs_voices] cache_fallback_empty key={cache_key}")
                return jsonify({"success": True, "voices": cached['data']})
        return jsonify({"success": True, "voices": voices})
    except Exception as e:
        try:
            print(f"[elevenlabs_voices] exception={str(e)}")
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/elevenlabs/models', methods=['GET'])
def elevenlabs_models():
    try:
        print('[ElevenLabs] models endpoint called')
        api_key = ELEVENLABS_API_KEY or (os.getenv('XI_API_KEY') or os.getenv('ELEVEN_LABS_API_KEY') or os.getenv('XI_API_KEY') or '')
        explicit = (request.args.get('api_key') or '').strip()
        if explicit:
            api_key = explicit
        if not api_key:
            return jsonify({"success": False, "error": "缺少ElevenLabs API密钥"}), 400
        base_url = 'https://api.elevenlabs.io'
        url = f"{base_url}/v1/models"
        cache_key = f"k={bool(api_key)}"
        now = time.time()
        try:
            cached = _models_cache.get(cache_key)
            if cached and (now - cached['ts'] < _cache_ttl_sec):
                print(f"[ElevenLabs] models cache_hit key={cache_key}")
                return jsonify({"success": True, "models": cached['data']})
        except Exception:
            pass
        headers = { 'xi-api-key': api_key }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            body_preview = ''
            try:
                body_preview = resp.text[:300]
            except Exception:
                pass
            try:
                cached = _models_cache.get(cache_key)
                if cached:
                    print(f"[ElevenLabs] models cache_fallback key={cache_key}")
                    return jsonify({"success": True, "models": cached['data']})
            except Exception:
                pass
            return jsonify({"success": False, "error": f"HTTP {resp.status_code}", "body": body_preview}), 500
        data = resp.json()
        items = []
        try:
            if isinstance(data, list):
                items = data
            else:
                items = data.get('models') or data.get('items') or []
        except Exception:
            items = []
        models = []
        for m in items:
            mid = (m.get('model_id') or m.get('id') or '').strip()
            name = (m.get('name') or '').strip()
            if mid:
                models.append({ 'id': mid, 'name': name or mid })
        print(f"[ElevenLabs] models count={len(models)}")
        try:
            _models_cache[cache_key] = { 'ts': now, 'data': models }
        except Exception:
            pass
        return jsonify({"success": True, "models": models})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 视频包装任务存储
packaging_tasks = {}
packaging_status = {}

import json
import hashlib
from datetime import datetime

class VideoPackager:
    def __init__(self):
        packaging_logger.info("VideoPackager initialized")

    def log_packaging_step(self, step, details=None, level='info'):
        """记录包装步骤日志"""
        message = f"[PACKAGING] {step}"
        if details:
            message += f" - {details}"

        if level == 'error':
            packaging_logger.error(message)
        elif level == 'warning':
            packaging_logger.warning(message)
        else:
            packaging_logger.info(message)

    def generate_ffmpeg_command(self, config, input_files, output_path):
        """根据VideoEditConfig生成FFmpeg命令"""
        self.log_packaging_step("开始生成FFmpeg命令", f"输出路径: {output_path}")

        commands = []
        inputs = []
        filters = []

        # 解析画布配置
        canvas = config.get('canvas', {})
        width = canvas.get('width', 540)
        height = canvas.get('height', 960)

        self.log_packaging_step("解析画布配置", f"尺寸: {width}x{height}, 背景色: {canvas.get('backgroundColor', '#000000')}")

        # 基础输出设置
        base_cmd = ['ffmpeg', '-y']

        # 跟踪输入文件索引
        input_index = 0

        # 处理背景层
        background = config.get('background', {})
        if background.get('fileUrl'):
            self.log_packaging_step("处理背景层", f"类型: {background.get('type', 'unknown')}")

            bg_file = input_files.get('background')
            if bg_file:
                # 转换API路径为实际文件路径
                if bg_file.startswith('/api/video/packaging/file/'):
                    filename = bg_file.split('/')[-1]
                    bg_file = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging', filename)
                    self.log_packaging_step("背景文件路径转换", f"API路径 -> 本地路径: {bg_file}")

                inputs.extend(['-i', bg_file])
                bg_input_index = input_index
                input_index += 1

                # 背景缩放和透明度
                opacity = background.get('opacity', 1.0)
                bg_filter = f"[{bg_input_index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
                if opacity < 1.0:
                    bg_filter += f",format=yuva444p,colorchannelmixer=aa={opacity}"
                    self.log_packaging_step("背景透明度设置", f"透明度: {opacity}")

                bg_filter += "[bg]"
                filters.append(bg_filter)
                self.log_packaging_step("背景滤镜生成", bg_filter)
            else:
                self.log_packaging_step("背景文件缺失", "input_files中没有找到background文件", "warning")
        else:
            self.log_packaging_step("跳过背景层", "未配置背景文件")

        # 处理主视频层
        video = config.get('video', {})
        if video.get('fileUrl'):
            self.log_packaging_step("处理主视频层", "检测到主视频配置")

            video_file = input_files.get('video')
            if video_file:
                # 转换API路径为实际文件路径
                if video_file.startswith('/api/video/packaging/file/'):
                    filename = video_file.split('/')[-1]
                    video_file = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging', filename)
                    self.log_packaging_step("主视频文件路径转换", f"API路径 -> 本地路径: {video_file}")

                inputs.extend(['-i', video_file])
                video_input_index = input_index
                input_index += 1

                # 视频位置和尺寸
                x = video.get('x', 0)
                y = video.get('y', 0)
                v_width = video.get('width', width)
                v_height = video.get('height', height)

                self.log_packaging_step("主视频尺寸配置", f"位置: ({x}, {y}), 尺寸: {v_width}x{v_height}")

                # 视频缩放
                video_opacity = video.get('opacity', 1.0)
                video_filter = f"[{video_input_index}:v]scale={v_width}:{v_height}"
                if video_opacity < 1.0:
                    video_filter += f",format=yuva444p,colorchannelmixer=aa={video_opacity}"
                    self.log_packaging_step("主视频透明度设置", f"透明度: {video_opacity}")

                video_filter += "[video]"
                filters.append(video_filter)
                self.log_packaging_step("主视频滤镜生成", video_filter)
            else:
                self.log_packaging_step("主视频文件缺失", "input_files中没有找到video文件", "warning")
        else:
            self.log_packaging_step("跳过主视频层", "未配置主视频文件")

        # 处理音频
        audio = config.get('audio', {})
        audio_input_index = None
        if audio.get('fileUrl'):
            self.log_packaging_step("处理音频层", "检测到音频配置")

            audio_file = input_files.get('audio')
            if audio_file:
                # 转换API路径为实际文件路径
                if audio_file.startswith('/api/video/packaging/file/'):
                    filename = audio_file.split('/')[-1]
                    audio_file = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging', filename)
                    self.log_packaging_step("音频文件路径转换", f"API路径 -> 本地路径: {audio_file}")

                inputs.extend(['-i', audio_file])
                audio_input_index = input_index
                input_index += 1

                # 音频处理
                volume = audio.get('volume', 1.0)
                audio_filter = ""
                if volume != 1.0:
                    audio_filter += f"volume={volume}"
                    self.log_packaging_step("音频音量设置", f"音量倍数: {volume}")

                # 淡入淡出
                fade_in = audio.get('fadeIn')
                if fade_in:
                    fade_duration = fade_in.get('duration', 1)
                    audio_filter += f",afade=t=in:st=0:d={fade_duration}"
                    self.log_packaging_step("音频淡入效果", f"淡入时长: {fade_duration}秒")

                fade_out = audio.get('fadeOut')
                if fade_out:
                    fade_start = fade_out.get('start', 5)
                    fade_duration = fade_out.get('duration', 1)
                    audio_filter += f",afade=t=out:st={fade_start}:d={fade_duration}"
                    self.log_packaging_step("音频淡出效果", f"开始时间: {fade_start}秒, 时长: {fade_duration}秒")

                if audio_filter:
                    full_audio_filter = f"[{audio_input_index}:a]{audio_filter}[audio_out]"
                    filters.append(full_audio_filter)
                    self.log_packaging_step("音频滤镜生成", full_audio_filter)
                else:
                    self.log_packaging_step("跳过音频滤镜", "音频无需特殊处理")
            else:
                self.log_packaging_step("音频文件缺失", "input_files中没有找到audio文件", "warning")
        else:
            self.log_packaging_step("跳过音频层", "未配置音频文件")

        # 合成视频层
        self.log_packaging_step("开始视频层合成", "配置视频叠加逻辑")
        if background.get('fileUrl') and video.get('fileUrl'):
            overlay_filter = "[bg][video]overlay=0:0[final_video]"
            filters.append(overlay_filter)
            self.log_packaging_step("视频叠加配置", "背景层 + 主视频层")
        elif video.get('fileUrl'):
            copy_filter = "[video]copy[final_video]"
            filters.append(copy_filter)
            self.log_packaging_step("视频叠加配置", "仅主视频层")
        elif background.get('fileUrl'):
            copy_filter = "[bg]copy[final_video]"
            filters.append(copy_filter)
            self.log_packaging_step("视频叠加配置", "仅背景层")
        else:
            self.log_packaging_step("警告", "没有配置任何视频层", "warning")

        # 添加滤镜链
        if filters:
            filter_complex = ";".join(filters)
            base_cmd.extend(['-filter_complex', filter_complex])
            self.log_packaging_step("滤镜链配置", f"滤镜数量: {len(filters)}")
            self.log_packaging_step("完整滤镜链", filter_complex)
        else:
            self.log_packaging_step("跳过滤镜链", "没有配置滤镜")

        # 输出映射
        video_streams = 0
        audio_streams = 0

        if video.get('fileUrl') or background.get('fileUrl'):
            base_cmd.extend(['-map', '[final_video]'])
            video_streams = 1
            self.log_packaging_step("视频流映射", "映射最终视频流")

        if audio.get('fileUrl') and audio_input_index is not None:
            if audio_filter:
                base_cmd.extend(['-map', '[audio_out]'])
                self.log_packaging_step("音频流映射", "映射处理后音频流")
            else:
                base_cmd.extend(['-map', f'{audio_input_index}:a'])
                self.log_packaging_step("音频流映射", f"映射原始音频流 {audio_input_index}")
            audio_streams = 1

        # 输出设置
        self.log_packaging_step("配置输出编码", "H.264视频 + AAC音频")
        base_cmd.extend([
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'medium',
            '-crf', '23',
            '-r', '30',
            output_path
        ])

        final_command = base_cmd + inputs
        self.log_packaging_step("FFmpeg命令生成完成", f"总参数数: {len(final_command)}, 输入流: {len(inputs)}, 视频流: {video_streams}, 音频流: {audio_streams}")

        return final_command

    def process_video_async(self, task_id, config, input_files):
        """异步处理视频包装"""
        try:
            print(f"[Packaging] Starting task {task_id}")
            print(f"[Packaging] Config: {json.dumps(config, indent=2)}")
            print(f"[Packaging] Input files: {json.dumps(input_files, indent=2)}")

            packaging_status[task_id] = {"status": "processing", "progress": 10}

            # 创建输出目录
            output_dir = ensure_writable_dir(os.path.join('outputs', 'packaging', task_id))
            print(f"[Packaging] Created output directory: {output_dir}")

            output_path = os.path.join(output_dir, "output.mp4")

            packaging_status[task_id] = {"status": "processing", "progress": 30}

            # 生成FFmpeg命令
            command = self.generate_ffmpeg_command(config, input_files, output_path)
            print(f"[Packaging] Generated command: {' '.join(command)}")

            packaging_status[task_id] = {"status": "processing", "progress": 50}

            # 检查输入文件是否存在
            for file_type, file_path in input_files.items():
                if file_path.startswith('/api/video/packaging/file/'):
                    filename = file_path.split('/')[-1]
                    full_path = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging', filename)
                    if not os.path.exists(full_path):
                        raise Exception(f"Input file not found: {full_path}")
                    print(f"[Packaging] Verified input file: {full_path}")

            packaging_status[task_id] = {"status": "processing", "progress": 60}

            # 执行FFmpeg命令
            print(f"[Packaging] Executing FFmpeg...")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )

            print(f"[Packaging] FFmpeg return code: {result.returncode}")
            print(f"[Packaging] FFmpeg stdout: {result.stdout}")
            print(f"[Packaging] FFmpeg stderr: {result.stderr}")

            if result.returncode != 0:
                error_msg = f"FFmpeg processing failed (code {result.returncode}): {result.stderr}"
                print(f"[Packaging] Error: {error_msg}")
                raise Exception(error_msg)

            packaging_status[task_id] = {"status": "processing", "progress": 90}

            # 验证输出文件
            if not os.path.exists(output_path):
                raise Exception(f"Output file not created: {output_path}")

            # 生成配置文件
            config_path = os.path.join(output_dir, "config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            print(f"[Packaging] Task {task_id} completed successfully")
            packaging_status[task_id] = {
                "status": "completed",
                "progress": 100,
                "output_url": f"/api/video/packaging/download/{task_id}",
                "config_url": f"/api/video/packaging/config/{task_id}"
            }

        except Exception as e:
            print(f"[Packaging] Task {task_id} failed: {str(e)}")
            packaging_status[task_id] = {
                "status": "error",
                "progress": 0,
                "error": str(e)
            }

# 全局视频包装器实例
video_packager = VideoPackager()

@app.route('/api/video/packaging/upload', methods=['POST', 'OPTIONS'])
def upload_packaging_file():
    """上传视频包装素材文件"""
    if request.method == 'OPTIONS':
        return Response(status=200)
    start_time = time.time()
    client_ip = request.remote_addr

    logger.info(f"[PACKAGING-UPLOAD] 开始上传 - 客户端IP: {client_ip}")

    try:
        if 'file' not in request.files:
            logger.warning(f"[PACKAGING-UPLOAD] 上传失败 - 未提供文件 - IP: {client_ip}")
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files['file']
        file_type = request.form.get('type', 'video')  # video, audio, background, watermark

        logger.info(f"[PACKAGING-UPLOAD] 文件信息 - 文件名: {file.filename}, 类型: {file_type}, IP: {client_ip}")

        if file.filename == '':
            logger.warning(f"[PACKAGING-UPLOAD] 上传失败 - 文件名为空 - IP: {client_ip}")
            return jsonify({"success": False, "error": "No file selected"}), 400

        if file and allowed_file(file.filename):
            # 创建唯一的文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{file_type}_{secure_filename(file.filename)}"

            # 创建上传目录
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging')
            os.makedirs(upload_dir, exist_ok=True)

            file_path = os.path.join(upload_dir, filename)

            # 记录上传开始
            logger.info(f"[PACKAGING-UPLOAD] 开始保存文件 - 目标路径: {file_path}")
            file.save(file_path)

            file_size = os.path.getsize(file_path)
            upload_time = time.time() - start_time

            logger.info(f"[PACKAGING-UPLOAD] 文件保存成功 - 文件大小: {file_size}字节, 耗时: {upload_time:.2f}秒, IP: {client_ip}")

            # 返回文件信息
            file_info = {
                "success": True,
                "filename": filename,
                "original_name": file.filename,
                "file_type": file_type,
                "file_path": file_path,
                "file_url": f"/api/video/packaging/file/{filename}",
                "file_size": file_size
            }

            return jsonify(file_info)

        logger.warning(f"[PACKAGING-UPLOAD] 文件类型不允许 - 文件名: {file.filename}, IP: {client_ip}")
        return jsonify({"success": False, "error": "File type not allowed"}), 400

    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"[PACKAGING-UPLOAD] 上传异常 - 错误: {str(e)}, 耗时: {error_time:.2f}秒, IP: {client_ip}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/video/packaging/process', methods=['POST', 'OPTIONS'])
def process_video_packaging():
    """处理视频包装"""
    if request.method == 'OPTIONS':
        return Response(status=200)
    start_time = time.time()
    client_ip = request.remote_addr

    logger.info(f"[PACKAGING-PROCESS] 开始处理 - 客户端IP: {client_ip}")

    try:
        data = request.get_json()

        if not data:
            logger.warning(f"[PACKAGING-PROCESS] 处理失败 - 未提供配置数据 - IP: {client_ip}")
            return jsonify({"success": False, "error": "No configuration provided"}), 400

        # 生成任务ID
        task_id = str(uuid.uuid4())

        # 解析配置
        config = data.get('config', {})
        input_files = data.get('input_files', {})

        logger.info(f"[PACKAGING-PROCESS] 任务创建 - 任务ID: {task_id}, IP: {client_ip}")
        logger.info(f"[PACKAGING-PROCESS] 配置信息 - 画布: {config.get('canvas', {})}")
        logger.info(f"[PACKAGING-PROCESS] 输入文件数量: {len(input_files)}, 文件类型: {list(input_files.keys())}")

        # 存储任务信息
        packaging_tasks[task_id] = {
            "config": config,
            "input_files": input_files,
            "created_at": datetime.now().isoformat(),
            "client_ip": client_ip
        }

        # 初始化状态
        packaging_status[task_id] = {"status": "queued", "progress": 0}

        logger.info(f"[PACKAGING-PROCESS] 启动异步处理 - 任务ID: {task_id}")

        # 启动异步处理
        thread = threading.Thread(
            target=video_packager.process_video_async,
            args=(task_id, config, input_files)
        )
        thread.daemon = True
        thread.start()

        setup_time = time.time() - start_time
        logger.info(f"[PACKAGING-PROCESS] 任务启动成功 - 任务ID: {task_id}, 准备耗时: {setup_time:.3f}秒, IP: {client_ip}")

        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": "queued"
        })

    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"[PACKAGING-PROCESS] 处理异常 - 错误: {str(e)}, 耗时: {error_time:.3f}秒, IP: {client_ip}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/video/packaging/status/<task_id>', methods=['GET'])
def get_packaging_status(task_id):
    """获取视频包装任务状态"""
    try:
        if task_id not in packaging_status:
            return jsonify({"success": False, "error": "Task not found"}), 404

        status = packaging_status[task_id]
        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": status
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/video/packaging/download/<task_id>', methods=['GET'])
def download_packaging_result(task_id):
    """下载视频包装结果"""
    try:
        if task_id not in packaging_status:
            return jsonify({"success": False, "error": "Task not found"}), 404

        status = packaging_status[task_id]
        if status.get('status') != 'completed':
            return jsonify({"success": False, "error": "Task not completed"}), 400

        # 构建文件路径
        output_path = f"outputs/packaging/{task_id}/output.mp4"

        if not os.path.exists(output_path):
            alt = os.path.join('/tmp', 'outputs', 'packaging', task_id, 'output.mp4')
            if not os.path.exists(alt):
                return jsonify({"success": False, "error": "Output file not found"}), 404
            output_path = alt

        def generate():
            with open(output_path, 'rb') as f:
                data = f.read(1024)
                while data:
                    yield data
                    data = f.read(1024)

        response = Response(
            generate(),
            mimetype='video/mp4',
            headers={
                "Content-Disposition": f"attachment; filename=packaged_video_{task_id}.mp4"
            }
        )
        return response

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/video/packaging/config/<task_id>', methods=['GET'])
def download_packaging_config(task_id):
    """下载视频包装配置"""
    try:
        if task_id not in packaging_tasks:
            return jsonify({"success": False, "error": "Task not found"}), 404

        config_path = f"outputs/packaging/{task_id}/config.json"

        if not os.path.exists(config_path):
            alt = os.path.join('/tmp', 'outputs', 'packaging', task_id, 'config.json')
            if not os.path.exists(alt):
                return jsonify({"success": False, "error": "Config file not found"}), 404
            config_path = alt

        return send_file(
            config_path,
            as_attachment=True,
            download_name=f"packaging_config_{task_id}.json"
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/video/packaging/file/<filename>', methods=['GET'])
def get_packaging_file(filename):
    """获取上传的包装文件"""
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'packaging', filename)

        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        return send_file(file_path)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/episode/narration', methods=['GET'])
def episode_narration_page():
    return render_template('episode_narration.html')

@app.route('/episode/narration/upload_batch', methods=['POST', 'OPTIONS'])
def episode_narration_upload_batch():
    try:
        if request.method == 'OPTIONS':
            return Response(status=200)
        if 'episode_files' not in request.files:
            return jsonify({'success': False, 'error': '没有选择文件'})
        files = request.files.getlist('episode_files')
        if not files or files[0].filename == '':
            return jsonify({'success': False, 'error': '没有选择文件'})
        user_prompt = (request.form.get('user_prompt') or (request.json or {}).get('user_prompt') or '').strip()
        model = (request.form.get('model') or (request.json or {}).get('model') or '').strip() or 'gemini-2.5-pro'
        batch_id = str(int(time.time() * 1000))
        out_dir = ensure_writable_dir(os.path.join(app.config['UPLOAD_FOLDER'], 'episode_narration', batch_id))
        results = []
        saved = []
        for i, f in enumerate(files):
            filename = secure_filename(f.filename)
            if not allowed_file(filename):
                results.append({'index': i, 'filename': filename, 'success': False, 'error': '文件格式不支持'})
                continue
            save_path = os.path.join(out_dir, filename)
            try:
                f.save(save_path)
                saved.append((i, filename, save_path))
            except Exception as e:
                results.append({'index': i, 'filename': filename, 'success': False, 'error': str(e)})

        episode_status[batch_id] = {
            'status': 'processing',
            'count': 0,
            'total': len(saved),
            'items': [{'index': idx, 'filename': fname, 'status': 'queued'} for (idx, fname, _p) in saved],
            'prompt': user_prompt,
            'model': model,
            'out_dir': out_dir
        }
        episode_results[batch_id] = [None] * len(saved)
        def _episode_run_batch(batch_id_, saved_, prompt_, model_):
            max_workers = max(1, min(len(saved_), (os.cpu_count() or 4)))
            if saved_:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_episode_analyze_one, batch_id_, idx, fname, path, prompt_, model_): (idx, fname, path) for (idx, fname, path) in saved_}
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            res = fut.result()
                        except Exception as e:
                            idx, fname, _p = futures[fut]
                            if isinstance(episode_results.get(batch_id_), list) and 0 <= idx < len(episode_results[batch_id_]):
                                episode_results[batch_id_][idx] = {'index': idx, 'filename': fname, 'success': False, 'error': str(e)}
                            else:
                                episode_results.setdefault(batch_id_, []).append({'index': idx, 'filename': fname, 'success': False, 'error': str(e)})
            try:
                st = episode_status.get(batch_id_, {})
                if st:
                    st['status'] = 'completed'
            except Exception:
                pass
        threading.Thread(target=_episode_run_batch, args=(batch_id, saved, user_prompt, model), daemon=True).start()
        return jsonify({'success': True, 'batch_id': batch_id, 'total_count': len(saved)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/episode/narration/batch/result/<batch_id>', methods=['GET'])
def episode_narration_batch_result(batch_id):
    try:
        res = episode_results.get(batch_id)
        if res is None:
            return jsonify({'success': False, 'error': '结果未找到'})
        return jsonify({'success': True, 'batch_id': batch_id, 'results': res, 'total_count': len(res)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/episode/narration/batch/status/<batch_id>', methods=['GET'])
def episode_narration_batch_status(batch_id):
    try:
        status = episode_status.get(batch_id)
        if status is None:
            return jsonify({'success': False, 'error': '状态未找到'})
        return jsonify({'success': True, 'batch_id': batch_id, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/episode/narration/retry_one', methods=['POST', 'OPTIONS'])
def episode_narration_retry_one():
    if request.method == 'OPTIONS':
        return Response(status=200)
    try:
        data = request.get_json(silent=True) or {}
        batch_id = str(data.get('batch_id') or '').strip()
        index = data.get('index')
        override_model = (data.get('model') or '').strip()
        override_prompt = (data.get('user_prompt') or '').strip()
        st = episode_status.get(batch_id)
        if not st:
            return jsonify({'success': False, 'error': '批次不存在'})
        items = st.get('items') or []
        if not isinstance(index, int) or index < 0 or index >= len(items):
            return jsonify({'success': False, 'error': '索引无效'})
        fname = items[index].get('filename')
        out_dir = st.get('out_dir')
        if not fname or not out_dir:
            return jsonify({'success': False, 'error': '文件信息缺失'})
        save_path = os.path.join(out_dir, fname)
        prompt = override_prompt or st.get('prompt') or ''
        model = override_model or st.get('model') or ''
        items[index]['status'] = 'processing'
        t0 = time.time()
        analyzer = VideoAnalyzer()
        try:
            result_text = analyzer.analyze_video_local(save_path, prompt, model=model, max_tokens=None, stream=False)
            t1 = time.time()
            duration_ms = int((t1 - t0) * 1000)
            res = {'index': index, 'filename': fname, 'success': True, 'result': result_text, 'model': model, 'duration_ms': duration_ms}
            if isinstance(episode_results.get(batch_id), list) and 0 <= index < len(episode_results[batch_id]):
                episode_results[batch_id][index] = res
            else:
                episode_results.setdefault(batch_id, []).append(res)
            items[index]['status'] = 'done'
            items[index]['duration_ms'] = duration_ms
            items[index]['model'] = model
            return jsonify({'success': True, 'result': res})
        except Exception as e:
            items[index]['status'] = 'failed'
            err = {'index': index, 'filename': fname, 'success': False, 'error': str(e)}
            if isinstance(episode_results.get(batch_id), list) and 0 <= index < len(episode_results[batch_id]):
                episode_results[batch_id][index] = err
            else:
                episode_results.setdefault(batch_id, []).append(err)
            return jsonify({'success': False, 'error': str(e)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # 创建templates目录
    if not os.path.exists('templates'):
        os.makedirs('templates')

    # 创建static目录
    if not os.path.exists('static'):
        os.makedirs('static')

    print("🚀 视频分析Web服务启动中...")
    try:
        print(f"🔑 Env presence: LAOZHANG_API_KEY={bool(os.getenv('LAOZHANG_API_KEY'))}, BIGMODEL_API_KEY={bool(os.getenv('BIGMODEL_API_KEY'))}, ELEVENLABS_API_KEY={bool(os.getenv('ELEVENLABS_API_KEY'))}")
    except Exception as _e:
        print(f"🔑 Env presence check error: {str(_e)}")
    print("📱 请在浏览器中访问: http://localhost:5001")
    print("⚠️  确保你的API密钥已正确配置")

    app.run(host='0.0.0.0', port=5001, debug=True)
SUPABASE_URL = (os.getenv('SUPABASE_URL') or '').strip()
SUPABASE_ANON_KEY = (os.getenv('SUPABASE_ANON_KEY') or '').strip()

def _validate_supabase_token(token):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY or not token:
        return None
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/user"
        headers = {
            'Authorization': f'Bearer {token}',
            'apikey': SUPABASE_ANON_KEY
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@app.before_request
def _auth_before_request():
    try:
        auth = {'token': None, 'user': None, 'valid': False}
        h = (request.headers.get('Authorization') or '').strip()
        token = ''
        if h.lower().startswith('bearer '):
            token = h[7:].strip()
        auth['token'] = token
        if token:
            user = _validate_supabase_token(token)
            if user:
                auth['user'] = user
                auth['valid'] = True
        g.__auth__ = auth
    except Exception:
        pass
