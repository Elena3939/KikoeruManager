# HTTP 高压控制面运行态缓冲

## 目标

HTTP 外链下载保持原下载并发、aria2 `split`、`max_connection_per_server` 和各平台并发配置不变。这里优化的是控制面：系统日志、任务中心、操作历史 lite、设置页和健康诊断接口在下载高压下仍能返回。

## 运行态配置

`runtime_buffer` 只影响运行期进度、事件和日志流批次：

```yaml
runtime_buffer:
  enabled: true
  backend: redis
  progress_flush_interval_seconds: 5.0
  log_stream_batch_size: 300
  log_stream_flush_ms: 250
```

- `backend=redis` 时优先写 Redis runtime / Stream。
- Redis 不可用时，任务运行态和事件写入进程内 memory fallback，已有下载不被中断。
- `backend=memory` 可用于本机临时排障，但重启后运行态缓存会丢失，PostgreSQL 仍保留终态。

## 数据落点

- 下载中的 `download_files`、`failed_files`、`download_runtime` 和 `progress_log` 优先进入 runtime buffer。
- PostgreSQL 中间态只保存轻量摘要和少量进度日志，避免每个 progress tick 都写大 JSON。
- `completed`、`failed`、`cancelled`、`waiting_manual`、`waiting_retry` 会强制完整落库，最终文件明细和错误原因不丢。

## 日志流保护

应用日志通过进程内有界队列异步写盘，业务线程不直接等待 `RotatingFileHandler`。队列默认保留最新 `10000` 条，达到上限时淘汰最旧记录，可通过 `KIKOERUMANAGER_LOG_QUEUE_SIZE` 调整。`GET /api/logs/stream/status` 的 `writer` 会返回队列容量、积压、丢弃计数和 listener 存活状态。

实时读取使用专用 `system-log-io` 线程池，全历史检索使用独立的 `system-log-search` 线程池，二者不占用默认 executor，也不会互相占满工作线程。SSE 按 `runtime_buffer.log_stream_flush_ms` 检查增量，每批最多推送 `runtime_buffer.log_stream_batch_size` 条；如果高压期间日志增量超过批次，响应会包含：

- `dropped_count`
- `original_count`
- `batch_size`
- `next_offset`

前端日志页会显示“流保护跳过 N”，并继续追最新 offset，避免一次性塞入几十 MB 日志导致白屏。

尾部日志窗口如果恰好从 traceback 中间开始，后端会在窗口内没有结构化日志头时最多向前补读 512KB，找到异常所属的真实时间和级别后再折叠堆栈。前端对仍以续行形式返回的内容继承相邻结构化日志时间；没有任何前后文时保持空时间，不伪造当前时间。

日志写盘队列不使用 Redis。这样 Redis 连接异常产生的诊断日志不会再次依赖 Redis，避免递归故障；Redis 仍负责任务运行态和实时业务事件。

## 大文本日志搜索

`GET /api/logs/search` 使用与实时流隔离的单 worker 扫描器，并返回不透明 `next_cursor`：

- 下一页必须原样传回 `next_cursor`，后端会从上次文件字节位置续扫，不再按匹配数量从头跳过。
- 游标绑定关键词、级别、扫描窗口和日志文件大小快照；日志轮转或截断后自动返回 `cursor_reset=true` 并从最新快照重新开始。
- 浏览器取消请求后，后端按最大 64KB 扫描片段检查取消信号，尽快释放搜索 worker。
- 无换行的大文本按 64KB 分片匹配，支持跨分片关键词；`logs` 保持单条 16KB 展示上限，`full_logs` 与其同序返回完整原文，日志页的省略行点击、复制和导出均优先使用原文。
- 前端用游标栈实现上一页；上一页会复用保存的页面起点游标，不使用数字偏移重新扫描。

## 诊断接口

- `GET /api/system/pressure`
- `GET /api/system/runtime-buffer/status`
- `GET /api/logs/stream/status`

这些接口不触发下载队列、远程库扫描或 aria2 批量轮询，只返回当前资源预算、runtime buffer、日志线程池、任务队列和数据库连接池状态。

## 明确不改

本优化不修改这些下载数据面配置：

- `http_downloader.max_concurrent_downloads`
- `http_downloader.split`
- `http_downloader.max_connection_per_server`
- `gofile_max_concurrent_downloads`
- ASMR / 百度网盘下载并发配置
