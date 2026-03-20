# 测试说明

## 1. 后端自动化测试

测试代码位于：

[backend/tests](D:/Clash%20Verge/KikoeruTool_Elena/backend/tests)

安装测试依赖：

```bash
cd backend
py -3 -m pip install -r requirements-test.txt
```

运行全部测试：

```bash
pytest
```

运行指定测试：

```bash
pytest tests/test_api.py -v
pytest tests/test_extract_service.py -v
pytest tests/test_task_engine.py -v
```

生成覆盖率：

```bash
pytest --cov=app --cov-report=term-missing
```

## 2. 前端验证

当前仓库没有单独的前端测试框架配置，至少应保证：

```bash
cd frontend
npm install
npm run build
```

前端构建通过，是提交前最基本的校验。

## 3. 打包前校验

建议至少执行：

```bash
py -3 -m py_compile desktop_app.py backend/build.py
cd frontend && npm run build
```

如果你改动了桌面入口、图标或打包逻辑，再执行一次：

```bat
build-release.bat
```

## 4. 手工测试清单

### 普通压缩包处理

- 上传压缩包
- 输入目录自动扫描
- 任务进入队列
- 元数据抓取成功
- 重命名与分类结果符合预期

### 查重与问题作品

- 直接重复能被识别
- 关联作品冲突能被识别
- 问题作品页面能展示详情

### 已有文件夹

- 能扫描已有文件夹目录
- 能提取 RJ 号
- 能执行增强查重
- 能按策略继续处理

### ASMR 同步

- 能扫描字幕目录
- 能预览可下载版本
- 能启动同步任务
- 失败任务可重试

### 库存打包

- 能保存打包配置
- 能启动打包
- 能取消或恢复任务

### 配置

- 前端保存配置成功
- 手动重载接口成功
- 运行时读取的是正确配置文件

## 5. 日志检查

出现异常时重点看：

- `data/app.log`
- 前端控制台
- API 文档中的接口返回

## 6. 测试建议

- 先用少量样本测试规则
- 再对真实库存做批量处理
- 查重、重命名、分类这三类改动最值得优先回归
