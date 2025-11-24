#!/bin/bash

# AI视频分析工具 - 项目管理脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 项目信息
PROJECT_NAME="AI视频分析工具"
VERSION="1.0.0"
DESCRIPTION="基于AI的智能视频内容识别与分析平台"

# 打印带颜色的信息
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo -e "${PURPLE}🎥 $PROJECT_NAME $VERSION${NC}"
    echo -e "${CYAN}$DESCRIPTION${NC}"
    echo
}

# 显示帮助信息
show_help() {
    print_header
    echo "用法: $0 [命令]"
    echo
    echo "可用命令:"
    echo "  setup      - 初始化项目环境"
    echo "  start      - 启动开发服务器"
    echo "  test       - 运行所有测试"
    echo "  test-unit  - 运行单元测试"
    echo "  test-int   - 运行集成测试"
    echo "  status     - 显示项目状态"
    echo "  clean      - 清理临时文件"
    echo "  deploy     - 部署项目"
    echo "  help       - 显示此帮助信息"
    echo
    echo "Git操作:"
    echo "  git-init    - 初始化Git仓库"
    echo "  git-status  - 显示Git状态"
    echo "  git-add     - 添加所有文件"
    echo "  git-commit  - 提交更改"
    echo "  git-push    - 推送到远程仓库"
    echo "  git-pull    - 拉取远程更改"
    echo
    echo "开发工具:"
    echo "  format     - 格式化代码"
    echo "  lint       - 代码检查"
    echo "  docs       - 生成文档"
    echo "  backup     - 备份项目"
    echo
}

load_env() {
    if [ -f ".env.local" ]; then
        set -a
        . ./.env.local
        set +a
    elif [ -f ".env" ]; then
        set -a
        . ./.env
        set +a
    fi
}

# 初始化项目环境
setup_project() {
    print_info "初始化项目环境..."

    # 检查Python版本
    if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
        print_error "未找到Python，请先安装Python"
        exit 1
    fi

    # 安装依赖
    print_info "安装依赖包..."
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        print_success "依赖安装完成"
    else
        print_warning "未找到requirements.txt文件"
    fi

    # 创建必要目录
    print_info "创建项目目录..."
    mkdir -p uploads temp logs

    # 检查API密钥配置
    print_info "检查配置..."
    if grep -q "YOUR_API_KEY" video_analyzer.py; then
        print_warning "请在video_analyzer.py中配置API密钥"
    else
        print_success "API密钥已配置"
    fi

    print_success "项目初始化完成！"
}

# 启动开发服务器
start_server() {
    print_info "启动开发服务器..."

    # 检查端口是否被占用
    if lsof -i :8080 &>/dev/null; then
        print_warning "端口8080已被占用，尝试使用端口8081..."
        export PORT=8081
    fi

    load_env
    print_info "服务器将在 http://localhost:${PORT:-5001} 启动"
    waitress-serve --host 0.0.0.0 --port ${PORT:-5001} app:app
}

serve() {
    load_env
    print_info "服务器将在 http://localhost:${PORT:-5001} 启动"
    waitress-serve --host 0.0.0.0 --port ${PORT:-5001} app:app
}

# 运行所有测试
run_tests() {
    print_info "运行所有测试..."

    # 单元测试
    test_unit

    # 集成测试
    test_integration

    print_success "所有测试完成！"
}

# 单元测试
test_unit() {
    print_info "运行单元测试..."

    # 检查核心功能
    if [ -f "test_video_analyzer.py" ]; then
        python test_video_analyzer.py
        print_success "视频分析器测试通过"
    fi

    if [ -f "test_streaming.py" ]; then
        python test_streaming.py
        print_success "流式响应测试通过"
    fi
}

# 集成测试
test_integration() {
    print_info "运行集成测试..."

    # 测试上传功能
    if [ -f "test_upload.py" ]; then
        python test_upload.py
        print_success "上传功能测试通过"
    fi

    # 测试批量上传
    if [f "test_batch_upload.py" ]; then
        python test_batch_upload.py
        print_success "批量上传测试通过"
    fi
}

# 显示项目状态
show_status() {
    print_header

    # Git状态
    print_info "Git状态:"
    if [ -d ".git" ]; then
        git status --short
        echo
        print_info "最近提交:"
        git log --oneline -5
        echo
    else
        print_warning "未初始化Git仓库"
        echo
    fi

    # Python环境
    print_info "Python环境:"
    python --version
    pip list | grep -E "(flask|openai|requests)" || echo "    未找到关键依赖"
    echo

    # 文件统计
    print_info "项目文件:"
    echo "    Python文件: $(find . -name "*.py" | wc -l)"
    echo "    HTML文件: $(find . -name "*.html" | wc -l)"
    echo "    配置文件: $(find . -name "*.txt" -o -name "*.json" | wc -l)"
    echo

    # 目录大小
    if [ -d ".git" ]; then
        print_info "仓库大小:"
        du -sh .git 2>/dev/null || echo "    无法计算.git大小"
    fi
}

# 清理临时文件
clean_project() {
    print_info "清理临时文件..."

    # 清理Python缓存
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true

    # 清理上传文件
    if [ -d "uploads" ]; then
        rm -rf uploads/*
        print_success "已清理上传目录"
    fi

    # 清理临时文件
    if [ -d "temp" ]; then
        rm -rf temp/*
        print_success "已清理临时目录"
    fi

    # 清理日志文件
    if [ -d "logs" ]; then
        rm -rf logs/*
        print_success "已清理日志目录"
    fi

    print_success "清理完成！"
}

# 代码格式化
format_code() {
    print_info "格式化Python代码..."

    # 使用black格式化（如果安装了的话）
    if command -v black &> /dev/null; then
        black *.py
        print_success "代码格式化完成"
    else
        print_warning "未安装black，跳过格式化"
    fi
}

# 代码检查
lint_code() {
    print_info "检查代码质量..."

    # 使用flake8检查（如果安装了的话）
    if command -v flake8 &> /dev/null; then
        flake8 *.py --max-line-length=100
        print_success "代码检查完成"
    else
        print_warning "未安装flake8，跳过代码检查"
    fi
}

# 生成文档
generate_docs() {
    print_info "生成项目文档..."

    # 这里可以添加文档生成工具
    print_info "文档目录结构:"
    echo "    📄 README.md - 项目说明文档"
    echo "    📄 git-workflow.md - Git工作流程指南"
    echo "    📄 requirements.txt - 依赖包列表"
    echo
}

# 备份项目
backup_project() {
    local backup_name="backup_$(date +%Y%m%d_%H%M%S)"
    local backup_dir="$HOME/backup"

    print_info "创建项目备份: $backup_name"

    # 创建备份目录
    mkdir -p "$backup_dir"

    # 排除不需要备份的目录和文件
    tar -czf "$backup_dir/$backup_name.tar.gz" \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='uploads' \
        --exclude='temp' \
        --exclude='logs' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        . 2>/dev/null

    if [ $? -eq 0 ]; then
        print_success "备份已保存到: $backup_dir/$backup_name.tar.gz"
    else
        print_error "备份失败"
    fi
}

# Git操作
git_init() {
    print_info "初始化Git仓库..."
    git init
    git add .
    git commit -m "🎉 Initial commit: $PROJECT_NAME"
    print_success "Git仓库初始化完成"
}

git_status() {
    print_info "Git状态:"
    git status
}

git_add() {
    print_info "添加所有文件到Git..."
    git add .
    print_success "文件已添加到暂存区"
}

git_commit() {
    local message="$1"
    if [ -z "$message" ]; then
        message="更新: $(date '+%Y-%m-%d %H:%M:%S')"
    fi
    print_info "提交更改: $message"
    git commit -m "$message"
}

git_push() {
    print_info "推送到远程仓库..."
    git push
}

git_pull() {
    print_info "从远程仓库拉取更改..."
    git pull
}

# 部署项目
deploy_project() {
    print_info "部署项目..."

    # 这里可以添加部署脚本
    print_warning "部署功能待实现"
}

# 主函数
main() {
    case "${1:-help}" in
        setup)
            setup_project
            ;;
        start)
            start_server
            ;;
        serve)
            serve
            ;;
        test)
            run_tests
            ;;
        test-unit)
            test_unit
            ;;
        test-int)
            test_integration
            ;;
        status)
            show_status
            ;;
        clean)
            clean_project
            ;;
        format)
            format_code
            ;;
        lint)
            lint_code
            ;;
        docs)
            generate_docs
            ;;
        backup)
            backup_project
            ;;
        deploy)
            deploy_project
            ;;
        git-init)
            git_init
            ;;
        git-status)
            git_status
            ;;
        git-add)
            git_add
            ;;
        git-commit)
            git_commit "$2"
            ;;
        git-push)
            git_push
            ;;
        git-pull)
            git_pull
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo "未知命令: $1"
            echo "使用 '$0 help' 查看可用命令"
            exit 1
            ;;
    esac
}

# 如果脚本被直接调用（不是被source）
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi