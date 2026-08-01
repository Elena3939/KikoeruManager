# Redis 运行态接入说明

Redis 只保存短期运行态、事件流和可恢复 dirty buffer；PostgreSQL 仍是最终事实源。

## 当前第一批接入范围

- 任务运行态快照：`task:runtime:{task_id}`，带 TTL。
- 实时事件 Stream：`events:stream`、`task-center:stream`。
- 特典补全 dirty buffer：`bonus-probe:cache:stream`。
- 任务中心 overview 短缓存：`task-center:overview`。

## 本地开发

默认配置要求 Redis 可用。需要临时跳过时，只能在本地配置中显式设置：

```yaml
redis:
  enabled: false
  required: false
```

不要在高压后台任务里静默回退到 PostgreSQL 高频写路径。
