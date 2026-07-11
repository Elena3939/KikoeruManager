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

系统日志接口使用专用 `system-log-io` bounded thread pool，不占用默认 executor。`/api/logs/stream` 每批最多推送 `runtime_buffer.log_stream_batch_size` 条；如果高压期间日志增量超过批次，响应会包含：

- `dropped_count`
- `original_count`
- `batch_size`
- `next_offset`

前端日志页会显示“流保护跳过 N”，并继续追最新 offset，避免一次性塞入几十 MB 日志导致白屏。

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
