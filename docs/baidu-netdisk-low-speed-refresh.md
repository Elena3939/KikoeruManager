# 百度网盘持续低速换链与断点续传

## 行为

- 分享文件进入 BaiduPCS-Go 下载前，`/share/transfer` 转存请求默认全局串行，避免批量任务同时建立多条百度 Web API TLS 连接。
- 转存遇到 SSL EOF、连接/读取超时、HTTP 429 或 5xx 时，默认按 2、5、12、30 秒退避重试 4 次；每次使用新 Session、新 `logid` 和新 `dp-logid`。
- 转存响应中断后会先通过 BaiduPCS-Go 查询临时目录；只有文件名和精确字节数都匹配才按实际转存成功继续下载，大小不匹配仍进入重试。
- 分享失效、提取码错误、Cookie 失效等百度业务错误不会重试。
- 转存错误中的 `sekey`、`logid`、`dp-logid`、`randsk`、`bdstoken` 会在写入任务、日志和通知前脱敏。
- 转存限制不改变下载限制：BaiduPCS-Go 每文件线程仍由 `max_parallel` 控制，全局同时下载文件数仍由 `max_download_load` 和 `resource_budget.network_download` 共同控制。
- 仅对已识别为 SVIP、文件大小不少于 512 MiB 的百度网盘下载启用低速监控。
- 使用下载字节增量计算窗口平均速度，不以 BaiduPCS-Go 单次输出的瞬时速度作为判定依据。
- 默认连续 180 秒低于 3 MB/s 时终止当前 BaiduPCS-Go 子进程，并重新执行 `download --mode locate` 获取下载线路。
- 换链过程中保持同一个远端临时转存目录、`work_dir` 和 `savedir`，保留 `.BaiduPCS-Go-downloading` 断点，由 BaiduPCS-Go 原地续传。
- 默认最多换链 2 次。达到上限后不再中止下载，保留当前线路继续完成，避免无限重试。
- 用户暂停或取消的优先级高于自动换链；任务结束后仍按原逻辑清理远端临时转存目录和本地工作目录。

## 配置

```yaml
baidu_netdisk:
  transfer_max_concurrency: 1
  transfer_retry_count: 4
  low_speed_refresh_enabled: true
  low_speed_threshold_mbps: 3
  low_speed_duration_seconds: 180
  low_speed_refresh_limit: 2
```

- `transfer_max_concurrency`：全局同时执行的分享转存请求数，范围 1～5，默认 1。
- `transfer_retry_count`：瞬时网络错误的额外重试次数，范围 0～8，默认 4。
- `low_speed_refresh_enabled`：是否启用 SVIP 大文件持续低速换链。
- `low_speed_threshold_mbps`：窗口平均速度阈值，范围 1～20 MB/s。
- `low_speed_duration_seconds`：持续低速判定窗口，范围 30～1800 秒。
- `low_speed_refresh_limit`：单文件最多换链次数，范围 0～5。

## 运行态

`download_runtime` 会同步暴露转存等待/执行/重试状态、转存尝试次数、下次重试等待时间，以及换链次数、换链上限、断点字节和低速窗口速度。任务仍保持 `processing`。
