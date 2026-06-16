## 2026-06-16 - Task: 修复百度网盘目录型分享预览误标错误
### What was done
- 修复百度网盘下载预览中目录节点被当成不可选错误项的问题。
- 允许带百度目录 `fs_id` 的目录节点作为可下载选择项提交，后端继续按现有逻辑递归展开目录文件下载。
- 调整全选、选中计数和提交 payload，避免父目录与子项重复提交。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/components/asmr/HttpDownloadPanel.vue`：百度预览树支持目录节点选择、计数和提交。
- `progress.md`：新增本轮修复记录。
- 回滚方式：还原 `frontend/src/components/asmr/HttpDownloadPanel.vue` 中本轮关于 `collectPreviewSelectableRows`、目录选择 key、选中项归一化和 `selectAllPreviewTreeFiles` 的改动；如不需要记录文件，可删除本轮新增的 `progress.md`。

## 2026-06-16 - Task: ASMR 同步后台下载小窗显示当前下载速度
### What was done
- 在 ASMR 同步页的后台下载小窗里展示当前下载速度。
- 百度网盘下载、HTTP 外链下载、ASMR 增强下载统一读取任务 `download_runtime.speed_bytes_per_sec`，当前任务无速度时聚合进行中任务速度。
- 速度仅在存在有效速度时显示，失败态仍保留“需要处理”提示。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/views/ASMRSync.vue`：后台下载卡片 meta 文案增加当前速度，并新增下载速度格式化与读取 helper。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/views/ASMRSync.vue` 中本轮关于 `backgroundDownloadMetaText`、`formatSpeed`、`getDownloadRuntime`、`getTaskDownloadSpeed`、`getBackgroundDownloadSpeed` 以及三个后台卡片 `metaText` 的改动。

## 2026-06-16 - Task: HTTP 外链下载成功入队后清理已提交链接
### What was done
- HTTP 外链下载和百度网盘下载在任务创建成功后，会自动从输入框里移除这次已经成功提交的链接。
- 对百度网盘链接额外兼容“链接 + 提取码下一行”的输入格式，清理时会连提取码一起移除。
- 清理后同步清空预览缓存，避免刷新后把已提交链接又恢复回来。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/components/asmr/HttpDownloadPanel.vue`：新增已提交链接清理逻辑，并给预览项附加输入来源用于精确回删。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/components/asmr/HttpDownloadPanel.vue` 中本轮新增的 `attachInputUrlToPreviewItems`、`clearStartedInputUrls`、`inputLineMatchesStartedItem` 以及 `start()` 里的清理调用。

## 2026-06-16 - Task: 修复 Transfer.it 断点续传速度虚高
### What was done
- 定位到 Transfer.it 专用下载器在断点续传时把已有 `.part` 文件大小计入本轮速度，导致工作台显示数百 MB/s。
- 调整 Transfer.it 速度采样为“本轮新增字节 / 采样间隔”，续传已有进度只参与已下载大小和进度，不再参与瞬时速度。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `backend/app/core/http_download_service.py`：修正 Transfer.it 下载循环里的 `speed_bytes_per_sec` 计算。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `backend/app/core/http_download_service.py` 中本轮关于 `speed_sample_at`、`speed_sample_bytes` 和 `speed_bytes_per_sec` 采样计算的改动。
