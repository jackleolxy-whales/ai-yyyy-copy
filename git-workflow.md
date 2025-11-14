# Git 工作流程指南

## 📋 基本工作流程

### 1. 功能开发流程
```bash
# 1. 创建功能分支
git checkout -b feature/新功能名称

# 2. 开发功能
# 进行代码修改...

# 3. 提交更改
git add .
git commit -m "feat: 添加新功能描述"

# 4. 推送分支
git push origin feature/新功能名称

# 5. 创建Pull Request
# 在GitHub/GitLab等平台创建PR
```

### 2. 修复问题流程
```bash
# 1. 创建修复分支
git checkout -b fix/问题描述

# 2. 修复问题
# 进行代码修改...

# 3. 提交修复
git add .
git commit -m "fix: 修复问题描述"

# 4. 推送分支
git push origin fix/问题描述

# 5. 创建Pull Request
```

### 3. 紧急修复流程
```bash
# 1. 直接在main分支修复（谨慎使用）
# 进行代码修改...

# 2. 提交修复
git add .
git commit -m "hotfix: 紧急修复描述"

# 3. 推送到main
git push origin main
```

## 🏷️ 提交信息规范

### 格式
```
<类型>(<范围>): <描述>

[可选的正文]

[可选的脚注]
```

### 类型说明
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式化（不影响功能）
- `refactor`: 重构代码
- `test`: 测试相关
- `chore`: 构建过程或辅助工具的变动
- `perf`: 性能优化
- `ci`: CI/CD相关

### 示例
```bash
git commit -m "feat(upload): 添加批量视频上传功能"
git commit -m "fix(ui): 修复按钮点击无响应问题"
git commit -m "docs(readme): 更新安装说明文档"
```

## 🔄 分支管理策略

### 主要分支
- `main`: 主分支，用于生产环境
- `develop`: 开发分支（可选）

### 功能分支
- `feature/*`: 新功能开发
- `fix/*`: 问题修复
- `hotfix/*`: 紧急修复

### 分支命名规范
```bash
feature/视频分析功能
feature/批量上传
fix/登录问题
hotfix/安全漏洞修复
```

## 📝 发布流程

### 1. 准备发布
```bash
# 1. 更新版本号
# 更新README.md或其他版本信息

# 2. 提交版本更新
git add .
git commit -m "chore: 更新版本号到v1.0.0"

# 3. 创建标签
git tag -a v1.0.0 -m "Release version 1.0.0"

# 4. 推送标签
git push origin v1.0.0
```

### 2. 版本回滚
```bash
# 1. 查看标签历史
git tag -l

# 2. 回滚到指定版本
git checkout v1.0.0

# 3. 创建新分支
git checkout -b hotfix/回滚修复

# 4. 推送修复
git push origin hotfix/回滚修复
```

## 🔍 代码审查清单

### 提交前检查
- [ ] 代码符合项目规范
- [ ] 功能测试通过
- [ ] 无明显bug或错误
- [ ] 文档更新完整
- [ ] 提交信息格式正确

### Pull Request检查
- [ ] 代码逻辑清晰
- [ ] 测试覆盖率充足
- [ ] 性能影响评估
- [ ] 安全性考虑
- [ ] 向后兼容性

## 🚀 持续集成

### 自动化检查
- 代码格式检查
- 静态代码分析
- 单元测试执行
- 集成测试验证

### 部署流程
1. 代码合并到main分支
2. 自动运行CI/CD流水线
3. 自动部署到测试环境
4. 人工验证后部署到生产环境

## 📊 版本管理

### 语义化版本控制
- `MAJOR.MINOR.PATCH`
- `1.0.0`: 主要版本（不兼容的API修改）
- `1.1.0`: 次要版本（向下兼容的功能性新增）
- `1.1.1`: 修订版本（向下兼容的问题修正）

### 版本发布周期
- **主要版本**: 根据重大功能更新
- **次要版本**: 每月或每季度
- **修订版本**: 根据bug修复需要

## 🔧 常用Git命令

### 查看信息
```bash
git status                    # 查看工作区状态
git log --oneline --graph   # 查看提交历史图形
git diff                      # 查看工作区与暂存区差异
git diff --staged             # 查看暂存区与仓库差异
```

### 撤销操作
```bash
git reset HEAD~1             # 撤销上一次提交（保留更改）
git reset --hard HEAD~1       # 撤销上一次提交（丢弃更改）
git revert <commit>           # 创建新提交撤销指定提交
git checkout -- <file>        # 撤销文件更改
```

### 分支操作
```bash
git branch -a                 # 查看所有分支
git branch <branch>           # 创建新分支
git checkout <branch>        # 切换分支
git merge <branch>           # 合并分支
git branch -d <branch>        # 删除分支
```

## 📋 常见问题解决

### 冲突解决
```bash
# 1. 查看冲突文件
git status

# 2. 手动编辑冲突文件
# 解决冲突标记 <<<<<<< ======= >>>>>>>

# 3. 标记冲突已解决
git add <冲突文件>

# 4. 提交合并
git commit -m "resolve: 解决合并冲突"
```

### 回退操作
```bash
# 撤销工作区更改
git checkout -- <file>

# 撤销暂存区更改
git reset HEAD <file>

# 撤销最近的提交
git reset --soft HEAD~1
```

## 📚 参考资料

- [Pro Git Book](https://git-scm.com/book)
- [GitHub Flow](https://guides.github.com/introduction/flow/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)