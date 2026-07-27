# 库存索引 watcher 容量与降级

本地库存使用宿主机 inotify 监听外部文件变化。容器共享宿主机的 inotify 容量；调整容器内 `nofile` 不能替代宿主机的 inotify 配置。

## 运行态诊断

访问 `GET /api/system/library-index/status`，检查 `watcher`：

- `watcher_mode=watchdog`：实时 observer 正常。
- `watcher_mode=inotify_limit`：宿主机 watch 或 instance 容量耗尽，实时 observer 已全部清理，进程保留有界轻量巡检，不自动触发全库重建。
- `start_errno` / `start_error`：本次启动失败原因。
- `inotify_limits`：容器读取到的 `max_user_watches` 与 `max_user_instances`。

## 宿主机调整

先在 Docker 宿主机查看当前值：

```sh
sysctl fs.inotify.max_user_watches
sysctl fs.inotify.max_user_instances
```

建议从下面的容量起步，再按宿主机上所有容器和进程的实际使用量调整：

```sh
sudo sysctl -w fs.inotify.max_user_watches=524288
sudo sysctl -w fs.inotify.max_user_instances=1024
```

普通 Linux 可写入 `/etc/sysctl.d/99-kikoerumanager-inotify.conf` 持久化：

```text
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=1024
```

然后执行 `sudo sysctl --system` 并重启 KikoeruManager 容器。群晖升级或重启可能覆盖 sysctl，需要用群晖任务计划在开机时重新设置。恢复后，诊断应回到 `watcher_mode=watchdog` 且 `live_events_available=true`。
