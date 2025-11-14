# 🎥 AI视频内容分析工具

一个基于AI的智能视频内容识别与分析平台，支持在线URL和本地文件两种输入方式，以及批量处理功能。

## ✨ 核心功能

- 🌐 **在线URL分析** - 支持输入视频链接进行分析
- 📁 **本地文件上传** - 支持直接上传本地视频文件进行分析
- 📚 **批量处理** - 支持同时上传并分析1-10个视频文件
- 🎨 **现代化界面** - 优雅的深色主题UI设计
- 🔄 **流式响应** - 实时显示分析过程和结果
- 📊 **独立API调用** - 每个视频分别调用AI进行分析

## 🚀 技术栈

- **后端**: Python 3.x + Flask
- **AI模型**: Gemini 2.5 Flash
- **前端**: HTML5 + CSS3 + JavaScript + Bootstrap 5
- **API**: OpenAI SDK + 自定义API接口

## 📦 安装与运行

### 1. 克隆项目
```bash
git clone https://github.com/yourusername/ai-video-analyzer.git
cd ai-video-analyzer
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置API密钥
在 `video_analyzer.py` 中设置你的API密钥：
```python
client = OpenAI(
    api_key="YOUR_API_KEY",  # 替换为实际API密钥
    base_url="https://api.laozhang.ai/v1"
)
```

### 4. 启动服务
```bash
python run.py
```

访问 http://localhost:8080 开始使用！

## 🎯 使用方法

### 方式一：在线URL分析
1. 选择"在线URL"选项
2. 输入视频URL地址
3. 设置分析要求
4. 点击"开始分析"

### 方式二：单文件上传
1. 选择"本地上传"选项
2. 选择本地视频文件
3. 设置分析要求
4. 点击"上传并分析"

### 方式三：批量上传分析
1. 选择"批量上传"选项
2. 选择多个视频文件（最多10个）
3. 设置统一的分析要求
4. 点击"批量上传并分析"

## 📋 支持格式

### 视频格式
- MP4, AVI, MOV, WMV, FLV, WebM, MKV

### 文件限制
- **单文件**: 最大 100MB
- **批量上传**: 总大小最大 500MB

## 🏗️ 项目结构

```
ai-video-analyzer/
├── app.py                 # Flask Web应用
├── video_analyzer.py     # 核心视频分析器
├── run.py               # 简化启动脚本
├── start_web.py         # 完整启动脚本
├── requirements.txt     # 依赖包列表
├── .gitignore          # Git忽略文件
├── README.md           # 项目说明文档
├── templates/          # HTML模板
│   └── index.html      # 主页面模板
├── static/             # 静态资源目录
├── uploads/            # 上传文件临时目录
├── test_*.py           # 测试脚本
└── example_usage.py    # 使用示例
```

## 🔧 API接口

### 单文件分析
- `POST /analyze` - URL方式分析
- `POST /upload` - 单文件上传分析

### 批量分析
- `POST /upload/batch` - 批量文件上传
- `GET /batch/status/{batch_id}` - 批次状态查询
- `GET /batch/results/{batch_id}` - 批次结果获取

### 其他接口
- `GET /health` - 服务健康检查
- `GET /status/{task_id}` - 任务状态查询

## 🎨 UI设计特色

- **深色主题** - 现代化的深蓝紫渐变配色
- **玻璃态效果** - 毛玻璃背景和微妙光效
- **响应式设计** - 适配各种设备屏幕
- **动画效果** - 流畅的交互动画和过渡
- **紫色主题** - 统一的紫色渐变色彩体系

## 🛠️ 开发说明

### 环境要求
- Python 3.8+
- Flask 2.0+
- OpenAI SDK 1.0+

### 开发模式
```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行开发服务器
python run.py
```

### 测试
```bash
# 运行功能测试
python test_streaming.py
python test_upload.py
python test_batch_upload.py
```

## 📊 核心功能特点

### 流式响应支持
- 支持实时显示AI分析过程
- 无token限制，获得完整分析结果
- 优化用户体验

### 批量处理机制
- 独立API调用每个视频
- 并行处理提高效率
- 统一分析要求应用
- 分区域展示结果

### 文件安全管理
- 自动清理临时文件
- 支持多种验证机制
- 保护用户隐私

## 🤝 贡献指南

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📝 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 📞 联系方式

如有问题或建议，请通过以下方式联系：
- 项目Issues: [GitHub Issues](https://github.com/yourusername/ai-video-analyzer/issues)
- 邮箱: your.email@example.com

## 🙏 致谢

- [OpenAI](https://openai.com/) - 提供强大的AI模型
- [Flask](https://flask.palletsprojects.com/) - Web框架
- [Bootstrap](https://getbootstrap.com/) - 前端框架
- [Font Awesome](https://fontawesome.com/) - 图标库

---

**注意**: 请确保在使用前正确配置API密钥，并遵守相关服务的使用条款。