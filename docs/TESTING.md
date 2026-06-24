# 测试指南

## 1. 后端测试

### 1.1 安装测试依赖

```bash
cd backend
venv\Scripts\python.exe -m pip install -r requirements-test.txt
```

### 1.2 运行单元测试

```bash
# 运行所有测试
venv\Scripts\python.exe -m pytest

# 运行特定测试
venv\Scripts\python.exe -m pytest tests/test_extract_service.py -v

# 运行测试并生成覆盖率报告
venv\Scripts\python.exe -m pytest --cov=app --cov-report=html
```

### 1.3 手动测试 API

启动后端服务：
```bash
venv\Scripts\python.exe -m app.main
```

访问 API 文档：
- Swagger UI: http://localhost:5555/docs
- ReDoc: http://localhost:5555/redoc

## 2. 前端测试

### 2.1 安装依赖

```bash
cd frontend
npm install
```

### 2.2 运行开发服务器

```bash
npm run dev
```

访问: http://localhost:5556

### 2.3 构建测试

```bash
npm run build
```

## 3. 集成测试（Docker）

### 3.1 构建并启动

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 3.2 测试文件准备

创建测试目录结构：
```bash
mkdir -p test_data/input
mkdir -p test_data/library
mkdir -p test_data/temp
```

## 4. 功能测试清单

### 4.1 基础功能测试

- [ ] **文件上传**
  - [ ] 拖拽文件到上传区域
  - [ ] 点击选择文件
  - [ ] 上传多个文件

- [ ] **任务管理**
  - [ ] 创建解压任务
  - [ ] 暂停/恢复任务
  - [ ] 取消任务
  - [ ] 查看任务进度

- [ ] **文件夹监视**
  - [ ] 启动监视器
  - [ ] 放入文件自动检测
  - [ ] 停止监视器

### 4.2 解压功能测试

准备测试压缩包：
1. **普通ZIP文件**（无密码）
2. **带密码ZIP**（密码：123456）
3. **分卷RAR**（part1.rar, part2.rar...）
4. **7z文件**
5. **错误后缀名文件**（如：test.zi, test.7）
6. **日文编码文件**（Shift_JIS编码）

测试步骤：
```bash
# 创建测试压缩包
cd test_data/input

# 创建测试文件
echo "test content" > test.txt

# 创建ZIP（无密码）
zip test_normal.zip test.txt

# 创建带密码ZIP
zip -P 123456 test_password.zip test.txt

# 创建分卷RAR（需要安装rar）
rar a -v1m test_multipart.rar test.txt

# 创建7z
7z a test_archive.7z test.txt
```

### 4.3 元数据获取测试

使用真实RJ号测试：
- RJ01071451
- RJ123456
- RJ12345678

### 4.4 重复检测测试

1. 处理一个作品到库存
2. 再次放入相同RJ号的压缩包
3. 检查是否进入问题作品列表

## 5. 性能测试

### 5.1 大文件测试

测试大文件（>4GB）解压：
```bash
# 创建大文件测试
dd if=/dev/zero of=large_file bs=1M count=5000
zip large_test.zip large_file
```

### 5.2 并发测试

同时上传多个文件，测试并发处理

## 6. 故障测试

### 6.1 异常场景

- [ ] 损坏的压缩包
- [ ] 不完整的分卷
- [ ] 磁盘空间不足
- [ ] 网络中断（元数据获取时）
- [ ] 权限不足

## 7. 测试脚本

### 7.1 快速测试脚本

```bash
#!/bin/bash
# test.sh - 快速测试脚本

echo "=== KikoeruManager 测试脚本 ==="

# 检查依赖
echo "检查依赖..."
python --version
docker --version
7z | head -1

# 启动服务
echo "启动服务..."
docker-compose up -d

# 等待服务启动
sleep 5

# 测试API
echo "测试API..."
curl http://localhost:5555/health

# 创建测试任务
echo "创建测试任务..."
curl -X POST http://localhost:5555/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/input/test.zip", "task_type": "auto_process"}'

echo "测试完成！"
```

## 8. 调试技巧

### 8.1 查看日志

```bash
# 后端日志
tail -f data/logs/app.log

# Docker日志
docker-compose logs -f kikoerumanager

# 系统日志（Linux）
journalctl -u kikoerumanager -f
```

### 8.2 数据库检查

```bash
# 进入数据库
psql -h 127.0.0.1 -p 5432 -U kikoerumanager -d kikoerumanager

# 查看任务表
SELECT * FROM tasks;

# 查看元数据缓存
SELECT rjcode, work_name FROM work_metadata;

# 查看库存索引状态和样例行
SELECT * FROM library_index_status;
SELECT library_id, relative_path, entry_type, size FROM library_index_entries LIMIT 20;
```

### 8.3 API调试

使用 curl 测试 API：

```bash
# 获取任务列表
curl http://localhost:5555/api/tasks | python -m json.tool

# 创建任务
curl -X POST http://localhost:5555/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/path/to/file.zip"}'

# 暂停任务
curl -X POST http://localhost:5555/api/tasks/{task_id}/pause

# 获取配置
curl http://localhost:5555/api/config | python -m json.tool
```

## 9. 测试数据生成

### 9.1 创建测试作品

```python
# generate_test_data.py
import os
import zipfile

def create_test_archive(filename, password=None, size_mb=1):
    """创建测试压缩包"""
    # 创建测试内容
    content = b"A" * (size_mb * 1024 * 1024)
    
    if password:
        # 创建带密码的zip
        import pyzipper
        with pyzipper.AESZipFile(filename, 'w', compression=pyzipper.ZIP_LZMA) as zf:
            zf.setpassword(password.encode())
            zf.writestr('test.txt', content)
    else:
        # 创建普通zip
        with zipfile.ZipFile(filename, 'w') as zf:
            zf.writestr('test.txt', content)
    
    print(f"Created: {filename}")

# 生成测试文件
if __name__ == "__main__":
    os.makedirs("test_data/input", exist_ok=True)
    
    create_test_archive("test_data/input/normal.zip")
    create_test_archive("test_data/input/password.zip", password="123456")
    create_test_archive("test_data/input/large.zip", size_mb=10)
    
    print("测试数据生成完成！")
```

## 10. API 重命名回归验证

API 重命名依赖 DLsite 元数据，验证时要覆盖 DLsite 不可用和缓存命中两类情况：

- DLsite 返回最小降级元数据时，单条 `/api/library/api-rename` 必须返回 `422`，目录保持原名，不能生成 `[][RJxxxx]` 或 RJ-only 名称。
- 批量 API 重命名必须走 `/api/library/batch-api-rename`，失败项标记 `skipped` 或失败原因，成功项继续执行，不能由前端并发打多个单条接口。
- 有有效缓存时，单条 API 重命名默认复用缓存；只有显式 `force_refresh` 才删除缓存并重新请求 DLsite。
- `use_japanese_metadata=true` 时，只有主元数据有效后才允许继续请求日语元数据。

推荐命令：

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_library_browser_api.py -q -k "api_rename"
```

前端批量入口改动后同时执行：

```powershell
cd frontend
npm run build
```

## 11. 字幕补配 Kikoeru 回归验证

字幕补配预检依赖 Kikoeru 判断原作是否已经收录、是否已有字幕，库存索引只负责定位实际候选目录。验证时要覆盖 Kikoeru 命中但 ready 库存索引暂未命中的情况：

- 简中翻译作能从 DLsite 关联链解析到原作时，Kikoeru 命中原作且缺字幕，预检不能按新作直接解压入库。
- 简中翻译作压缩包里没有字幕文件时，即使原作缺字幕，也必须转入问题作品，不能跳过关联重复后继续入库。
- Kikoeru 查询不稳定时，预检必须保持待重试，不能自动降级为普通解压。
- Kikoeru 已确认原作有字幕时，翻译作应按重复作品处理。
- Kikoeru tracks 查询返回 `total_track_count=0` 时，应识别为空壳作品并阻止字幕补配入队。

推荐命令：

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_linked_subtitle_import_service.py -q
```

## 12. 持续集成测试

### 12.1 GitHub Actions 配置

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: |
          cd backend
          python -m pip install -r requirements.txt
          python -m pip install -r requirements-test.txt
      - name: Run tests
        run: |
          cd backend
          python -m pytest --cov=app
  
  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Node
        uses: actions/setup-node@v2
        with:
          node-version: 18
      - name: Install dependencies
        run: |
          cd frontend
          npm install
      - name: Build
        run: |
          cd frontend
          npm run build
```

---

## 测试检查表

在开始使用前，请确保：

- [ ] Docker 和 Docker Compose 已安装
- [ ] 7-Zip 已安装并添加到 PATH
- [ ] 配置文件路径正确设置
- [ ] 目录权限正确（可读写）
- [ ] 网络连接正常（用于获取元数据）
- [ ] 磁盘空间充足（建议至少10GB可用）

如有问题，请查看日志文件或联系开发者。

## 9. 媒体预览

- `/api/library/browser/preview` 的视频、音频、图片响应不进入 gzip，避免 `Range` 预览被压缩流干扰。
