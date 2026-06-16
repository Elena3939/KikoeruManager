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

## 2026-06-16 - Task: 目录差异工作台提交按钮加载动画
### What was done
- 将目录差异工作台底部提交按钮接入统一 `StatefulButton`，点击提交后展示加载、成功、失败状态动画。
- 保留原有深色主按钮外观，并让提交失败返回错误态，避免失败后按钮误显示成功反馈。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`：提交按钮改用 `StatefulButton`，补充提交态图标和尺寸稳定样式。
- `frontend/src/views/Conflicts.vue`：将 `submitMerge` 作为 Promise 动作传入工作台，并返回成功 / 失败结果驱动按钮状态。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/components/conflicts/ConflictMergeWorkbench.vue` 中本轮 `StatefulButton`、`submitAction`、`handleSubmitClick` 和 `.cmw-submit-*` 样式改动；还原 `frontend/src/views/Conflicts.vue` 中 `:submit-action` 与 `submitMerge` 返回值改动。

## 2026-06-16 - Task: ASMR 设置测试查重按钮加载动画
### What was done
- 将外部服务设置里的“测试查重 RJ”按钮接入统一 `StatefulButton`，查询期间展示旋转加载态，完成后展示成功 / 失败反馈。
- 移除该按钮原有的专用 Lottie 状态绑定，避免与 Kikoeru 连接测试、Token 获取、清缓存共用忙碌态时互相干扰。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：测试查重按钮改用 `StatefulButton`，新增独立 `kikoeruDuplicateTesting` 状态并清理旧 Lottie 代码。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中本轮关于 `StatefulButton`、`kikoeruDuplicateTesting`、`runKikoeruDuplicateTest` 返回值和 `.service-duplicate-test-*` 样式的改动；如需恢复旧视觉，再恢复原 Lottie 按钮模板、导入和生命周期绑定。

## 2026-06-16 - Task: 日志进度条显示具体业务行为
### What was done
- 将系统日志里的任务进度条标题从短任务 ID 改为具体业务行为。
- 进度步骤本身包含 RJ 号时直接显示，例如 `获取元数据 RJ01607252`；步骤不带 RJ 时，从同任务的 `任务ID` 日志补齐 RJ，显示为 `重命名 RJ01607252` 等业务标题。
- 保留原始进度详情、状态、持续时间和百分比展示，不改变后端任务日志格式。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
- Node 样例校验：`任务 f600dbdb...: 获取元数据 RJ01607252 (65%)` 解析为 `获取元数据 RJ01607252`；同任务 `重命名文件夹` 可通过 `任务ID` 上下文补齐为 `重命名 RJ01607252`。
### Notes
- `frontend/src/views/Logs.vue`：新增任务 ID 到 RJ 的上下文映射，并生成进度条业务标题。
- `frontend/src/components/common/SystemLogTerminal.vue`：进度条标题改为显示 `taskProgress.title`，不再渲染短任务 ID。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/views/Logs.vue` 中本轮新增的进度 RJ 解析、业务动作标题生成和 `parseTaskProgressLog` 参数变更；还原 `frontend/src/components/common/SystemLogTerminal.vue` 中进度条标题渲染改动；如不需要记录文件，可删除本轮新增的 `progress.md` 段落。

## 2026-06-16 - Task: 修复日志页半屏卡住与滚动粘住
### What was done
- 修复系统日志 SSE 续连后只剩少量增量日志时，页面看起来加载到半屏就停住的问题。
- 当实时日志窗口少于 50 行时，自动回填最近历史日志，避免只显示续连后的几条新增日志。
- 内容不足一屏时自动解除 `history pinned`，恢复自动滚动状态，避免看起来不能上下滑动。
- 放宽实时日志批量刷新间隔，减少高频日志时前端主线程被连续刷新抢占。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/views/Logs.vue`：新增实时日志稀疏窗口回填、回填防抖，并调整 SSE 批处理节流。
- `frontend/src/components/common/SystemLogTerminal.vue`：内容不足一屏时同步清除 pinned 状态并恢复自动滚动。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/views/Logs.vue` 中本轮关于 `LOG_FLUSH_INTERVAL`、`MIN_LIVE_HISTORY_BACKFILL_LINES`、`backfillLiveHistoryIfSparse` 与 SSE 回填调用的改动；还原 `frontend/src/components/common/SystemLogTerminal.vue` 中 `syncScrollPinState` 和不足一屏滚动状态同步改动；如不需要记录文件，可删除本轮新增的 `progress.md` 段落。

## 2026-06-16 - Task: 修复批量 API 重命名重复提交与前端超时误报
### What was done
- 根据服务器日志定位批量 API 重命名失败表现：批量请求会串行刷新 DLsite 元数据，15 到 16 项耗时约 150 到 220 秒；同一批路径还出现过两次并发提交，导致一批成功后另一批按旧路径返回 0/N。
- 后端对完全相同的批量 API 重命名请求增加运行中复用，同一批路径正在处理时，后续重复请求等待并返回同一份结果，不再重复拉取元数据或重复重命名。
- 前端批量 API 重命名取消 axios 本地超时限制，避免大批量慢请求被前端误报为失败。
- 未改动任何命名策略：模板读取、日语元数据优先级、`RenameService._compile_name()`、`_sanitize_filename()` 和最终命名格式都保持原样。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\api\routes.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `backend/app/api/routes.py`：为 `/api/library/batch-api-rename` 增加相同请求的 in-flight 结果复用，避免重复提交互相打架。
- `frontend/src/api/index.js`：批量 API 重命名请求改为不使用 axios 本地超时。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `backend/app/api/routes.py` 中 `_BATCH_API_RENAME_INFLIGHT`、`_batch_api_rename_request_key` 和批量 API 重命名任务复用相关改动；还原 `frontend/src/api/index.js` 中 `batchApiRename` 的 timeout 改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-16 - Task: 提升批量 API 重命名吞吐
### What was done
- 把批量 API 重命名里每个条目的“获取元数据 + 生成新名称”改成有限并发，默认最多 4 路同时跑。
- 保持最终命名逻辑完全不变：仍然使用同一套模板、同一套日语元数据优先级、同一套文件名清理。
- 真正落盘的批量 `rename` 仍保持聚合执行，没有改成并行重命名，避免同目录竞争。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\api\routes.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `backend/app/api/routes.py`：批量 API 重命名计划生成阶段接入 `asyncio.Semaphore(4)` + `asyncio.gather`。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `backend/app/api/routes.py` 中批量 API 重命名计划生成的并发改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 优化任务中心删除过滤文件树显示
### What was done
- 明确任务中心文件树里的过滤命中项为已删除项展示，按钮和统计文案从“被过滤”改为“已删除”。
- 修复目录被过滤删除时，目录下快照子项仍显示为正常文件的问题；现在会继承目录删除态，并显示“随目录删除”。
- 优化删除态视觉：整行灰底、左侧灰色标识条、图标灰阶、文件名和大小删除线、删除徽标，暗色模式下同样生效。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/views/Tasks.vue`：过滤目录按目录类型映射，并将目录删除态传播给其子项文件树行。
- `frontend/src/components/tasks/TaskDetailPane.vue`：调整任务详情文件树删除态文案、徽标、浅色和暗色样式。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/views/Tasks.vue` 中本轮关于 `removedByDirectory`、`mapFilteredItems`、`isSameOrInsideTaskTreePath` 和目录删除态传播的改动；还原 `frontend/src/components/tasks/TaskDetailPane.vue` 中本轮关于删除态文案、徽标和样式的改动；删除本轮新增的 `progress.md` 段落。
