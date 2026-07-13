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

## 2026-06-17 - Task: 优化系统日志解压进度详情
### What was done
- 解压任务进度不再只写“解压中 xx%”，现在会从 7z 实时输出中提取当前正在解压的条目名，并写入任务当前步骤和进度日志。
- 对长路径 / 长文件名做中间截断，避免超过任务表 `current_step` 字段长度，同时保留文件名尾部用于判断具体文件。
- 日志页任务进度条标题不再压成单独“解压”，会优先显示 `解压 RJxxxx` 或压缩包名；详情行展示“当前文件: xxx · 速度 / 剩余时间”。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\extract_service.py backend\app\core\task_engine.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `backend/app/core/extract_service.py`：解析 7z 进度输出中的当前条目名，修正 stdout 进度 chunk 解码和 CR 分隔处理，并限制进度步骤长度。
- `frontend/src/views/Logs.vue`：解压进度标题补 RJ / 压缩包名，详情行展示当前解压文件和速度 / 剩余时间。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `backend/app/core/extract_service.py` 中本轮新增的进度文本截断、7z 当前条目解析、进度 chunk 解码和 `progress_callback` 消息拼接改动；还原 `frontend/src/views/Logs.vue` 中本轮新增的解压进度标题 / 详情解析逻辑；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 修复本地库存删除确认大小读取旧索引
### What was done
- 本地库存删除预检不再读取库存索引里的目录大小，改为直接按当前文件系统递归统计大小、文件数和目录数。
- 批量删除预检同样改为本地实时统计，并保留父目录覆盖子路径时只计一次的去重逻辑。
- 本地删除、批量删除和移动完成后，会刷新受影响外层目录的索引聚合大小，避免外层列表继续显示旧大小。
- 本地文件树内容读取保持走当前文件系统，只有外层文件夹大小展示继续允许复用索引。
- 远程库存删除预检未改动，仍可使用索引或远程 stat，避免远程递归统计拖慢操作。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\library_manager.py`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py::test_local_realtime_reads_ignore_stale_index_for_browse_and_folder_contents tests\test_library_browser_api.py::test_local_delete_refreshes_outer_folder_index tests\test_library_browser_api.py::test_local_file_move_refreshes_source_and_target_outer_folder_index -q`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py tests\test_library_index_self_mutation.py tests\test_library_index_snapshot_store.py tests\test_library_index_performance_behavior.py -q`：未全量通过；失败集中在既有测试环境/旧用例问题，包括 SQLite 无法渲染 PostgreSQL JSONB、`library_index_write` 与旧断言 `database_write` 不一致、测试 monkeypatch 的 `_schedule_index_mutation_flush_locked` 不接收 `delay_seconds`。
### Notes
- `backend/app/core/library_manager.py`：新增本地删除预检的文件系统实时统计，让本地单删 / 批删确认使用该统计结果，并在删除 / 移动后刷新外层目录索引聚合。
- `backend/tests/test_library_browser_api.py`：补充旧索引大小错误时，本地删除预检仍返回磁盘真实大小，以及删除 / 移动后刷新外层目录索引的回归断言。
- `docs/INTRODUCTION.md`：说明本地库存外层大小可用索引展示，但确认和文件树读取走实时文件系统，写操作会刷新外层聚合。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `backend/app/core/library_manager.py` 中 `_local_delete_preview_from_filesystem`、本地单删 / 批删预检调用、外层目录索引刷新 helper 与删除 / 移动后的刷新调用；还原 `backend/tests/test_library_browser_api.py` 中本轮删除预检和外层索引刷新断言；还原 `docs/INTRODUCTION.md` 中本轮新增说明；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 修复库存文件管理展开和目录索引统计
### What was done
- 文件管理弹窗的“展开全部”支持异步展开懒加载子目录，按钮点击后会逐层加载并展开，不再只展开已加载节点。
- 本地文件管理浅层目录读取优先使用库存索引目录行里的 `size` / `file_count`，避免超级目录实时递归统计拖慢页面；递归读取仍走当前文件系统，删除确认也走当前文件系统实时统计。
- 库存索引 self-mutation 写入路径维护祖先目录 `size` / `file_count`，覆盖文件 upsert、删除、同库移动、跨库移动、子树 upsert。
- 批量目录数统计和父链聚合更新改为 PostgreSQL 批量 SQL，避免按目录数量放大查询；测试也切到 PostgreSQL，不再用 SQLite 路径验证索引逻辑。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\library_index\snapshot_store.py backend\app\core\library_index\service.py backend\app\core\library_manager.py`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py tests\test_library_browser_api.py -q`：31 passed。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `frontend/src/components/library/FolderContentsDialog.vue`：展开全部改为异步递归加载子目录，并增加展开中状态防重复点击。
- `backend/app/core/library_manager.py`：本地浅层文件树 / 移动目录浏览优先读索引；删除确认改为实时文件系统统计。
- `backend/app/core/library_index/snapshot_store.py`：为文件 upsert、删除、同库 / 跨库移动维护祖先目录大小和文件数，批量统计改为 PostgreSQL SQL。
- `backend/app/core/library_index/service.py`：子树 upsert 只把子树根目录新旧聚合差量同步到外层父目录，避免扫描时重复聚合。
- `backend/tests/test_library_browser_api.py`：补本地浅层读索引、递归读实时、删除确认读实时的回归断言。
- `backend/tests/test_library_index_self_mutation.py`：补父目录聚合随文件变更、删除、子树 upsert、同库 / 跨库移动更新的 PostgreSQL 回归断言。
- `progress.md`：追加本轮最终修复记录。
- 回滚方式：还原上述文件中本轮关于异步展开、浅层索引读取、实时删除确认、父链聚合 self-mutation 和对应测试的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 优化库存页社团聚合视图切换控件
### What was done
- 将库存页标题旁“目录视图 / 社团视图”的双按钮切换，改成单个二元 switch 控件。
- 去掉原有硬边框、分段按钮和亮色块，改为中性色轨道 + 滑块 + 两侧文字状态，减少标题区视觉噪音。
- 补充暗色模式和移动端样式，避免被库存页全局 scope 切换样式覆盖。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
- 内置浏览器打开 `http://127.0.0.1:5173/library` 做视觉检查时，当前后端 `/library/libraries`、`/library/browser/stats` 等接口返回 500，导致库存页 mounted hook 中断并空屏；因此未完成真实页面截图确认。
### Notes
- `frontend/src/views/Library.vue`：标题区视图切换控件改为单个 `role="switch"` 的二元开关，并补浅色 / 暗色 / 移动端样式。
- `progress.md`：追加本轮 UI 调整记录。
- 回滚方式：还原 `frontend/src/views/Library.vue` 中本轮关于 `lib-view-mode-toggle` 模板和样式的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 统一库存索引使用边界
### What was done
- 明确只有库存内路径使用库存索引；非库存目录预览恢复原实时文件 IO，不再因为没有库存归属被拒绝。
- 库存浏览 / 搜索继续优先走索引：远程库存搜索和普通名称搜索现在可先查 `library_index`，只有索引命中才短路；索引不可用或空命中会回落到原文件系统 / 群晖搜索。
- 字幕补配、字幕爬取、字幕工作台检查、上传预览、百度上传预览等快速变化的小额文件场景统一传 `prefer_index=false`，保证读取当前文件系统状态。
- 旧重命名 / 删除接口统一进入 `LibraryManager`，只允许库存内路径执行，并触发已有库存 self-mutation；HTTP 外链下载和百度网盘下载服务本身不参与库存索引。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend/app/core/library_manager.py backend/app/api/routes.py backend/app/core/library_index/service.py backend/app/core/library_index/snapshot_store.py backend/app/core/rj_subtitle_service.py backend/app/core/linked_subtitle_import_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_library_index_fts.py tests/test_library_index_local_scanner.py tests/test_library_index_performance_behavior.py tests/test_library_index_remote_scanner.py tests/test_library_index_self_mutation.py tests/test_library_index_snapshot_store.py tests/test_library_browser_api.py -q`：65 passed。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
### Notes
- `backend/app/core/library_manager.py`：库存搜索扩展为 RJ / 名称索引优先并按当前搜索目录过滤；本地浅层文件树支持 `prefer_index` 开关，删除预检保持实时 IO。
- `backend/app/api/routes.py`：浏览文件树接口接收 `prefer_index`；旧 `folder-contents` 对非库存路径保留实时 IO，对库存路径转入 `LibraryManager`；旧重命名 / 删除接口只允许库存内路径。
- `backend/app/core/rj_subtitle_service.py`：RJ 字幕远程扫描、清理、检查和匹配读取文件树时显式关闭索引。
- `backend/app/core/linked_subtitle_import_service.py`：字幕导入等待、摘要和远程候选读取时显式关闭索引。
- `frontend/src/api/index.js`：文件夹内容 API 支持 `preferIndex`、`libraryId` 和 `recursive` 参数。
- `frontend/src/components/circle/CircleLocalUploadDialog.vue`：本地上传源目录读取关闭索引。
- `frontend/src/components/common/ServerUploadPreviewDialog.vue`：服务端上传预览读取关闭索引。
- `frontend/src/components/subtitle-import/SubtitleImportWorkbench.vue`：字幕工作台检查字幕目录和音频目录时关闭索引。
- `frontend/src/views/Library.vue`：字幕检查 / 百度上传预览相关目录读取关闭索引。
- `backend/tests/test_library_browser_api.py`：补库存浅层默认索引、`prefer_index=false` 实时读取、非库存目录旧接口实时 IO、索引名称搜索范围过滤回归。
- `backend/tests/test_library_index_performance_behavior.py`：修正索引队列调度测试 mock，兼容当前延迟调度参数。
- `backend/tests/test_library_index_snapshot_store.py`：断言库存索引写入使用 `library_index_write` 资源维度。
- `progress.md`：追加本轮索引边界记录。
- 回滚方式：还原上述文件中本轮关于 `prefer_index` / `preferIndex`、索引搜索优先、非库存实时 IO fallback、旧接口库存内重命名删除、相关测试断言的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 取消启动自动重建库存索引
### What was done
- 移除后端启动 8 秒后自动补齐远程库存索引的后台任务，进入系统 / 重启服务不会再自动排队全量重建索引。
- 删除 `needs_initial_remote_rebuild` 启动修复判定入口，避免后续代码再从该路径恢复自动扫描。
- 保留手动 `/api/library/index/rebuild` 能力，用户点击重建索引时仍会正常执行。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend/app/api/routes.py backend/app/core/library_index/service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_library_index_self_mutation.py tests/test_library_browser_api.py -q`：33 passed。
- `rg -n "needs_initial_remote_rebuild|_bootstrap_remote_library_indexes|启动修复|schedule_rebuild_remote\\(" backend/app backend/tests -g "*.py"`：确认只剩手动重建接口调用 `schedule_rebuild_remote`。
### Notes
- `backend/app/api/routes.py`：删除 `_bootstrap_remote_library_indexes()` 和 startup 中的自动排队调用。
- `backend/app/core/library_index/service.py`：删除启动自动修复专用的 `needs_initial_remote_rebuild()`。
- `backend/tests/test_library_index_self_mutation.py`：调整索引状态测试，明确无旧快照时只表示读路径不可用，不代表自动重建。
- `progress.md`：追加本轮取消自动重建记录。
- 回滚方式：还原上述三个文件中本轮删除的启动自动修复逻辑和测试断言；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 修复启动后库存索引卡同步中
### What was done
- 确认运行态数据库里 `kikoeru` 等库存残留 `syncing` 状态，其中 `kikoeru` 的 `total_entries=5000` 与页面“正在同步 · 5,000 项”一致。
- 启动和状态查询只纠正上次进程中断遗留的 `syncing`，不触发远程库重建；首建中断会标记为 `error` 并释放“同步中”按钮。
- 对曾经完整建过索引的库存，若重建中断且本进程没有对应后台任务，则恢复为 `ready` 并从 `library_index_entries` 重算统计，避免半截进度污染统计。
- 后台重建任务改为按 library 追踪，某个库存真实同步时不会阻止其它库存清理旧 `syncing`。
- 已对运行态库执行一次状态纠正，当前 `library_index_status` 不再有 `syncing` 残留。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\library_index\service.py app\core\library_index\snapshot_store.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py -q`：21 passed。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py tests\test_library_browser_api.py tests\test_library_index_performance_behavior.py tests\test_library_index_snapshot_store.py -q`：60 passed。
- `cd backend && .\venv\Scripts\python.exe -` 查询运行态 `library_index_status`：`syncing_count 0`。
- `rg -n "needs_initial_remote_rebuild|_bootstrap_remote_library_indexes|schedule_rebuild_remote\\(|schedule_rebuild_local\\(|normalize_all_interrupted_syncing_statuses|normalize_interrupted_syncing_status" backend/app backend/tests -g "*.py"`：确认启动只做状态纠正，`schedule_rebuild_*` 只剩手动重建入口和方法定义。
### Notes
- `backend/app/api/routes.py`：startup 增加库存索引中断状态纠正，不再自动重建。
- `backend/app/core/library_index/service.py`：新增中断 `syncing` 归一化、按库后台任务追踪和状态查询兜底。
- `backend/app/core/library_index/snapshot_store.py`：新增从 entries 表重算库存索引聚合统计的方法。
- `backend/tests/test_library_index_self_mutation.py`：补首建中断转 error、已完成快照重建中断恢复 ready 的回归测试。
- `progress.md`：追加本轮状态卡住修复记录。
- 回滚方式：还原上述文件中本轮关于 `normalize_interrupted_syncing_status`、`calculate_library_stats`、startup 状态纠正和新增测试的改动；如需恢复运行态状态，可手动重新点击前端“重建索引”。

## 2026-06-17 - Task: 修复库存社团聚合目录进入和表格切换动画
### What was done
- 社团聚合视图里的虚拟目录行不再进入桌面框选 / 拖拽捕获流程，点击社团名、图标或行空白都能触发进入下一层。
- 为社团虚拟目录行增加可打开状态 class，鼠标样式明确表现为可进入目录。
- 库存表格增加 `Transition` 切换动画，目录 / 社团视图切换、进入社团下级、分页和页大小变化都会触发淡入 + 轻微位移动画。
- 社团作品层不再同时显示作品汇总行和真实路径行；有真实路径时只展示聚合出的路径候选，避免同一个 RJ 看起来重复。
- 点击社团作品下的真实路径时，改为在应用内切回目录视图并定位该路径，不再弹“远程库存 / FileStation”提示。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
- `cd frontend && npm run build`：补充真实路径定位语义后再次通过。Vite warning 同上。
- 内置浏览器尝试打开 `http://127.0.0.1:5173/library` 验证点击时，当前本地页面返回空 body，未能完成真实点击截图确认。
### Notes
- `frontend/src/views/Library.vue`：绕开社团虚拟目录的框选捕获，单击虚拟目录直接调用 `openFolder()`，表格切换 key 纳入视图模式、社团虚拟路径、当前页和页大小，并补表格 swap 动画样式；社团作品层只展示真实路径候选，点击真实路径走 `locateCircleLocation()` 切回目录视图定位。
- `progress.md`：追加本轮修复记录。
- 回滚方式：还原 `frontend/src/views/Library.vue` 中本轮关于 `Transition`、`libraryTableKey`、`isCircleVirtualDirectoryRow`、虚拟目录点击处理、社团作品层 rows 构造、真实路径定位和 `lib-file-table-swap` / `library-row-openable` 样式的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 收口库存社团聚合目录包装显示
### What was done
- 社团聚合里的单路径作品行恢复使用真实 RJ 文件夹名，不再用 RJ 号和作品标题重新拼名称。
- 单路径作品行下方不再显示库存路径；只有重复 RJ 聚合展开到具体路径时才显示真实路径说明。
- 社团视图的行路径改为 `circle:/...` 虚拟映射路径，面包屑保持社团包装路径；真实操作统一通过 `circle_real_path` 和 `circle_real_library_id` 回落到原库存路径。
- 单路径作品进入后复用原库存浏览接口读取真实目录内容，并把子项包装成社团虚拟路径；重复 RJ 先展示真实位置，进入某个位置后再浏览该真实目录内容。
- 移除本轮社团刷新对全页 `loading` 的绑定和表格 swap 过渡，避免把“显示模式切换”做成额外加载 / 样式系统。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
- 内置浏览器打开 `http://127.0.0.1:5174/library`：页面标题正常，控制台 error 数为 0。
### Notes
- `frontend/src/views/Library.vue`：修正社团聚合行名、元信息、虚拟路径解码 / 面包屑、真实操作路径归一化，以及单路径 / 重复路径目录进入逻辑。
- `progress.md`：追加本轮社团聚合收口记录。
- 回滚方式：还原 `frontend/src/views/Library.vue` 中本轮关于 `circleBuild*Path`、`circleDecodeVirtualPath`、`circleLocationFolderName`、`circleLoad*ChildRows`、`normalizeLibraryActionRow`、`getCircleRowMetaText`、`openFolder`、`navigateToPath`、`goToParent`、社团面包屑和移除表格 swap/loading 的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 禁用远程群晖库存索引
### What was done
- 远程 `synology_filestation` 库不再创建、重建、读取库存索引；手动重建接口对远程库直接拒绝，远程索引 service 入口改为 disabled no-op。
- 库存全局搜索中，本地库继续走 PostgreSQL 库存索引，远程群晖库强制走 FileStation fallback；旧远程索引行不会再被搜索接口返回。
- 库存统计会净化旧远程 `library_index/syncing` 缓存，远程库页面不再显示“正在同步 / 已索引 N 项 / 重建索引”，改为 FileStation 实时浏览语义。
- 前端隐藏远程库索引徽章和快照按钮，搜索失败提示不再建议远程库重建索引；移动弹窗和设置文案也同步收口。
- 文档同步说明：本地库存用库存索引，Synology FileStation 远程库存走群晖原生接口。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\library_manager.py app\core\library_index\service.py app\core\library_index\__init__.py app\core\library_index\remote_scanner.py app\core\asmr_resource_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py tests\test_library_browser_api.py -q`：35 passed。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py tests\test_library_index_remote_scanner.py -q`：22 passed。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval、chunk 体积 warning。
### Notes
- `backend/app/api/routes.py`：远程库索引重建接口改为拒绝；状态接口对远程返回 disabled；索引搜索和全局搜索排除远程索引并回落 FileStation。
- `backend/app/core/library_manager.py`：库存索引限定本地库使用；远程 stats 旧索引缓存转为 FileStation 占位；远程搜索、删除、批删和文件树读取不再保留可达远程索引路径。
- `backend/app/core/library_index/service.py`：`rebuild_remote` / `schedule_rebuild_remote` 改为 disabled no-op，防止后续误调用扫群晖。
- `backend/app/core/library_index/__init__.py`、`backend/app/core/library_index/remote_scanner.py`：更新模块说明，标明远程扫描器仅兼容保留。
- `backend/app/core/asmr_resource_service.py`：远程入库后的索引通知注释改为兼容本地路径，避免误解远程库会写索引。
- `frontend/src/views/Library.vue`：远程库隐藏索引徽章和快照按钮，统计文案改为 FileStation 实时浏览，远程索引状态事件不再写入统计卡。
- `frontend/src/components/library/LibraryIndexBadge.vue`：远程库不挂载、不轮询、不触发重建。
- `frontend/src/components/library/LibraryMoveDialog.vue`：远程库跳过索引状态检查。
- `frontend/src/components/library/LibrarySearchBox.vue`、`frontend/src/components/library/LibrarySearchOverlay.vue`：远程搜索失败提示改为检查网络 / 群晖凭据，不再提示重建索引。
- `frontend/src/components/settings/SystemSettingsPanel.vue`：远程资源预算说明移除远程库存索引重建。
- `docs/INTRODUCTION.md`：同步库存索引边界说明。
- `progress.md`：追加本轮远程索引禁用记录。
- 回滚方式：还原上述文件中本轮关于远程库索引 disabled/no-op、远程 FileStation fallback、前端隐藏远程索引 UI 和文档说明的改动；删除本轮新增的 `progress.md` 段落。如需恢复旧远程索引能力，还需要重新启用 `/api/library/index/rebuild` 对 `synology_filestation` 的 `schedule_rebuild_remote` 调用。

## 2026-06-17 - Task: 修复文件管理弹窗未展开目录显示 0 个文件
### What was done
- 文件管理弹窗的浅层目录读取不再把“未展开 / 未统计”的目录伪装成 `0` 个文件，避免刚打开显示 0、展开后又变成真实数量。
- 本地库存实时 IO 和群晖 FileStation 实时 IO 都返回 `null` 表示目录计数未知；本地库存索引路径仍保留索引里的准确计数。
- 前端兼容旧接口可能返回的 `0/0` 占位值，未展开目录显示“未统计”，展开加载子项后再显示真实文件数；真实空目录显示“空目录”。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\library_manager.py app\api\routes.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q`：14 passed。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval、chunk 体积 warning。
### Notes
- `backend/app/core/library_manager.py`：本地 / 群晖浅层 `folder_contents` 的目录项计数改为未知值，不再返回假 `0`。
- `frontend/src/components/library/FolderContentsDialog.vue`：目录副标题优先区分未知、空目录和已知计数，并兼容旧占位响应。
- `backend/tests/test_library_browser_api.py`：补浅层实时目录项不返回假计数的回归断言。
- `progress.md`：追加本轮文件管理弹窗计数修复记录。
- 回滚方式：还原上述三个代码文件中本轮关于目录 `file_count/folder_count`、`normalizeShallowItem`、`getRowSubtitle` 和新增断言的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 文件管理弹窗目录计数后台水合
### What was done
- 文件管理弹窗恢复“打开就显示真实目录计数”的体验，但把重活拆成后台水合队列，首屏优先补当前可见目录，没滚到的目录低速慢慢算。
- 后端目录摘要接口补了 `file_count / folder_count / partial`，本地走文件系统递归，群晖远程走 FileStation 分层遍历，不借库存索引。
- 对超大目录加了条目数和时间上限，超限就返回部分结果并在前端显示 `+`，避免大库打开卡死。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\library_manager.py app\api\routes.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q`：14 passed。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval、chunk 体积 warning。
### Notes
- `backend/app/core/library_manager.py`：新增本地 / 远程目录摘要统计 helper，支持部分结果和缓存。
- `backend/app/api/routes.py`：`compute-folder-size(s)` 接收 `include_counts`、`max_entries`、`max_seconds`，并把摘要结果回给前端。
- `frontend/src/api/index.js`：批量目录大小接口支持目录计数参数。
- `frontend/src/components/library/FolderContentsDialog.vue`：新增可见目录优先、后台限流补统计的队列调度，目录副标题支持“统计中 / 未统计 / 部分结果”。
- `backend/tests/test_library_browser_api.py`：补 `include_counts` 返回文件数 / 子目录数的回归断言。
- `progress.md`：追加本轮目录计数后台水合记录。
- 回滚方式：还原上述四个代码文件中本轮关于摘要接口、队列调度和 `include_counts` 的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-17 - Task: 收紧社团聚合真实路径直用
### What was done
- 社团聚合的真实目录行不再被整页虚拟路径展开逻辑拖慢，传入真实行时直接使用真实路径，只有社团壳和包装行才请求后端展开真实目标。
- 社团视图里的批量右键菜单恢复按真实选中行生效，真实目录可继续走字幕、删除过滤、移动、重命名等原有功能。
- 顶部工具按钮在社团视图下不再被“当前库存是否可写”误拦，最终是否可执行仍由真实目标路径和目标库存判定。
- 补了社团聚合“后端包装展示、真实路径执行”的产品说明。
### Testing
- `backend\\venv\\Scripts\\python.exe -m py_compile backend\\app\\core\\library_circle_aggregation_service.py backend\\app\\api\\routes.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 chunk 体积、VueUse pure 注释、lottie-web eval 相关 warning。
- 内置浏览器打开 `http://localhost:5556/library`：页面存在社团切换开关、当前页抓字幕 / 删除过滤按钮和社团根列表。
### Notes
- `frontend/src/views/Library.vue`：收紧 `resolveCircleActionRows` 的展开边界，恢复社团视图右键批量态，修正社团视图按钮可用性和清理旧的虚拟页口径。
- `docs/INTRODUCTION.md`：补社团聚合仅包装展示、真实路径直用的说明。
- `progress.md`：追加本轮社团聚合收口记录。
- 回滚方式：还原本轮对 `frontend/src/views/Library.vue` 的社团真实路径收紧、右键批量态、按钮可用性和旧口径清理改动；删除本轮新增的 `progress.md` 段落；同步撤销 `docs/INTRODUCTION.md` 对社团聚合说明的补充。

## 2026-06-18 - Task: 修复社团补全拥有态表迁移漏列
### What was done
- 修复 PostgreSQL 兼容迁移表清单漏掉 `library_owned_works` 的问题，后续启动迁移会为社团补全本地拥有态表补齐 `folder_size / file_count / owned_paths / has_local_subtitles / subtitle_file_count / subtitle_dir` 等列。
- 增加回归测试，锁定兼容迁移必须把 `library_owned_works` 传入拥有态表迁移，避免服务器升级后社团补全详情继续因缺列 500。
- 排查服务器日志，确认截图报错来自 `/api/circle-completion/circles/*` 查询 `library_owned_works.folder_size`，运行库当前仍需通过容器内 psql 或受限白名单连接执行补列 SQL。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\models\database.py tests\test_database_compat_migrations.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_database_compat_migrations.py -q`：未通过；当前测试环境在 `conftest.py` 收集期创建 PostgreSQL 测试库时卡住 / 无输出退出。
- `cd backend && .\venv\Scripts\python.exe -` 执行最小迁移探针：通过，确认 `_migrate_compat_schema()` 会探测并传递 `library_owned_works`。
### Notes
- `backend/app/models/database.py`：兼容迁移 `_existing_tables()` 清单加入 `library_owned_works`。
- `backend/tests/test_database_compat_migrations.py`：新增兼容迁移表清单回归测试。
- `progress.md`：追加本轮数据库迁移修复记录。
- 回滚方式：还原上述两个代码文件中本轮关于 `library_owned_works` 迁移探测和回归测试的改动；删除本轮新增的 `progress.md` 段落。服务器运行库如已手工补列，回滚代码不会自动删除数据库列，需另行执行对应 `ALTER TABLE ... DROP COLUMN`，通常不建议回删兼容列。

## 2026-06-18 - Task: 调查并缓解 Gofile 429 下载失败
### What was done
- 排查截图里的 Gofile 下载失败链路，确认失败项来自 aria2 下载阶段，`status=429` 是 Gofile CDN 限流，`No URI available` 是 aria2 在当前直链不可用后的失败信息。
- Gofile 下载提交给 aria2 时改为单连接单分片，并补浏览器 User-Agent 和 Referer，避免服务器批量大文件下载时按全局 8 分片放大连接数触发限流。
- 补充 Gofile aria2 参数回归测试，锁定 Gofile 不再使用全局高分片配置。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py`：通过。
- `backend\venv\Scripts\python.exe -` 执行最小 Gofile aria2 参数断言：通过，确认 `split=1`、`max-connection-per-server=1`、User-Agent、Referer 和 Cookie header 均生效。
- `cd backend && ..\backend\venv\Scripts\python.exe -m pytest tests\test_http_download_service.py::test_gofile_aria2_options_use_conservative_connections -q -s`：未完成；当前本机 PostgreSQL `127.0.0.1:5432` 未开放，`tests/conftest.py` 在收集期创建 PostgreSQL 测试引擎时阻塞超时。
- `git diff --check -- backend/app/core/http_download_service.py backend/tests/test_http_download_service.py docs/INTRODUCTION.md`：通过；仅输出 Windows 工作区既有 LF/CRLF 提示。
### Notes
- `backend/app/core/http_download_service.py`：为 Gofile 的 aria2 options 加保守单连接、浏览器 User-Agent 和 Referer。
- `backend/tests/test_http_download_service.py`：新增 Gofile aria2 参数回归测试。
- `docs/INTRODUCTION.md`：补充 Gofile 下载使用保守单连接以降低 CDN 429 的说明。
- `progress.md`：追加本轮 Gofile 下载失败调查和缓解记录。
- 回滚方式：还原上述三个代码 / 文档文件中本轮关于 Gofile aria2 参数、回归测试和说明文字的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-18 - Task: 回退 Gofile 单连接下载缓解
### What was done
- 按要求回退上一轮 Gofile 单连接 / 单分片 aria2 参数改动，Gofile 下载重新使用全局 HTTP 下载参数。
- 移除对应的 Gofile 专用参数回归测试和文档说明，保留原有 Gofile 解析、预览、Cookie header 逻辑不变。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py`：通过。
- `git diff --check -- backend/app/core/http_download_service.py backend/tests/test_http_download_service.py docs/INTRODUCTION.md progress.md`：通过；仅输出 Windows 工作区既有 LF/CRLF 提示。
### Notes
- `backend/app/core/http_download_service.py`：撤销 Gofile aria2 options 的 `split=1`、`max-connection-per-server=1`、User-Agent、Referer 专用覆盖。
- `backend/tests/test_http_download_service.py`：删除上一轮新增的 Gofile 单连接参数测试。
- `docs/INTRODUCTION.md`：删除上一轮新增的 Gofile 保守单连接说明。
- `progress.md`：追加本轮回退记录。
- 回滚方式：如需恢复上一轮缓解，重新为 Gofile aria2 options 覆盖单连接单分片并补回对应测试和文档说明。

## 2026-06-18 - Task: 调整 Gofile 下载为 2 并发 5 分片
### What was done
- Gofile 下载不再使用全局 8 分片，改为每个文件固定 5 分片、最多 5 个同源连接。
- 同一个 HTTP 下载任务内，Gofile 最多同时运行 2 个 aria2 gid；第 3 个及以后先以暂停状态提交，前面完成或失败后自动放行下一个。
- 保留原有 Gofile 分享解析、文件选择、Cookie header、失败大小校验和重试链路不变。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py backend\tests\test_http_download_service.py`：通过。
- `backend\venv\Scripts\python.exe -` 执行最小 Gofile helper 验证：通过，确认 Gofile options 为 5 分片，且有 1 个运行中 Gofile 时只放行 1 个暂停 gid。
- `backend\venv\Scripts\python.exe -` 执行模拟 3 个 Gofile 文件的下载任务断言：核心断言通过，确认第 3 个 gid 先 `pause=true`、前面释放后 `aria2.unpause`；脚本结束阶段任务指标写库因本机 PostgreSQL 未开放输出连接失败日志，不影响本轮 Gofile 调度断言。
- `git diff --check -- backend/app/core/http_download_service.py backend/tests/test_http_download_service.py docs/INTRODUCTION.md progress.md`：通过；仅输出 Windows 工作区既有 LF/CRLF 提示。
### Notes
- `backend/app/core/http_download_service.py`：新增 Gofile aria2 分片常量和 Gofile gid 暂停 / 自动补位逻辑。
- `backend/tests/test_http_download_service.py`：新增 Gofile 5 分片和 2 并发调度回归测试。
- `docs/INTRODUCTION.md`：同步 Gofile 单任务 2 并发、每文件 5 分片说明。
- `progress.md`：追加本轮 Gofile 下载策略调整记录。
- 回滚方式：还原上述三个代码 / 文档文件中本轮关于 `_GOFILE_ARIA2_*`、Gofile `pause/unpause` 调度、测试和说明文字的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-18 - Task: 增加 Gofile 下载单独配置
### What was done
- 在 HTTP 下载配置里新增 Gofile 专用“并发文件数”和“分片数”，默认保持 2 个文件并发、每文件 5 分片。
- 设置页 HTTP 下载面板新增 Gofile 并发文件和 Gofile 分片数两个数字配置项，保存后后端下载调度实时读取这些值。
- Gofile aria2 参数和同任务内暂停 / 自动补位逻辑改为读取配置，并补回归测试覆盖非默认配置。
- 产品说明同步为 Gofile 可在设置页单独配置，避免继续被理解为写死策略。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py backend\app\config\settings.py backend\tests\test_http_download_service.py`：通过。
- `backend\venv\Scripts\python.exe -` 执行最小 Gofile 配置调度脚本：通过，确认 `gofile_split=4` 时 aria2 使用 4 分片，`gofile_max_concurrent_downloads=1` 时第 2 / 第 3 个 gid 先暂停并按顺序 `unpause`。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- backend/app/core/http_download_service.py backend/app/config/settings.py backend/tests/test_http_download_service.py frontend/src/components/settings/HttpDownloadSettingsPanel.vue frontend/src/composables/useSettingsDraft.js docs/INTRODUCTION.md`：通过；仅输出 Windows 工作区既有 LF/CRLF 提示。
- 未跑 pytest；当前 `backend/tests/conftest.py` 在收集期创建 PostgreSQL 测试引擎，本机测试库不可用会卡在数据库连接。
### Notes
- `backend/app/config/settings.py`：HTTP 下载配置新增 Gofile 并发文件数和分片数默认值。
- `backend/app/core/http_download_service.py`：Gofile 分片和单任务并发补位改为读取配置。
- `backend/tests/test_http_download_service.py`：补默认值断言和非默认 Gofile 调度 / 分片回归测试。
- `frontend/src/components/settings/HttpDownloadSettingsPanel.vue`：Gofile API Token 下新增两个专用数字配置项。
- `frontend/src/composables/useSettingsDraft.js`：前端默认配置补齐 Gofile 专用默认值。
- `docs/INTRODUCTION.md`：同步 Gofile 支持设置页单独配置的说明。
- `progress.md`：追加本轮 Gofile 单独配置记录。
- 回滚方式：还原上述代码 / 文档文件中本轮关于 `gofile_max_concurrent_downloads`、`gofile_split`、设置页控件、测试和说明文字的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-18 - Task: 修复社团补全本地拥有态漏算 RaRo 作品
### What was done
- 核对 `\\Elena\ASMR\RaRo` 和 `\\Elena\AMSR\RaRo`，确认两个 RaRo 目录直接 RJ 文件夹合计 250 个，明显高于页面显示的 136 个本地拥有。
- 定位漏算原因：全量 `library_owned_works` 重建只按本地目录 RJ 解析出的 canonical 写快照，没有像增量入库一样反查 `CircleWork.linked_rjcodes`；当本地目录 RJ 是翻译版 / 关联版时，详情页按 `CircleWork.canonical_rjcode` 左连接会漏标 owned。
- 修复全量本地拥有态同步：库存索引命中某个 RJ 后，同时写入 resolver canonical 和所有关联到该 RJ 的社团作品 canonical，使左侧统计与右侧详情统一口径。
- 新增回归测试覆盖“本地命中 RJ 与社团作品 canonical 不一致”时仍写入相关 `LibraryOwnedWork` 的场景。
### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\circle_completion_service.py backend\tests\test_circle_completion_owned_sync.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q`：未完成；当前测试环境在 `tests/conftest.py` 收集期连接 PostgreSQL 测试库时超时。
- `cd backend && .\venv\Scripts\python.exe -` 执行等价拥有态同步断言：通过，确认单个库存 RJ 命中会同时写入 resolver canonical 和 `CircleWork.linked_rjcodes` 反查到的作品 canonical。
### Notes
- `backend/app/core/circle_completion_service.py`：全量本地拥有态同步增加 RJ 到社团作品 canonical 的反向映射，并将同一个库存命中合并写入所有相关 canonical 快照。
- `backend/tests/test_circle_completion_owned_sync.py`：新增 canonical 不一致时全量拥有态同步不漏写的回归测试。
- `progress.md`：追加本轮 RaRo 本地拥有态漏算修复记录。
- 回滚方式：还原上述两个代码 / 测试文件中本轮关于 `sync_local_owned_index()` 反向 canonical 写入和新增测试的改动；删除本轮新增的 `progress.md` 段落。服务器端如果已部署本修复，回滚后需重新触发本地拥有态同步才会覆盖运行库快照。

## 2026-06-18 - Task: 修复新社团首次索引后本地命中未落库
### What was done
- 排查 `シルトクレーテ` 索引日志，确认任务 `f9c4c7eb-8cf7-4893-a8be-21201f44d209` 在库存索引阶段实际命中 `local_index_owned_count=147`、`local_index_hit_count=153`，但详情页仍显示已满足 0。
- 定位原因：首次建立社团索引时，索引开头的全量 `sync_local_owned_index()` 还看不到当前社团的 `CircleWork` 行；后续 `_apply_library_index_owned_state_to_items()` 虽然在内存中识别出本地拥有态，但没有同步写入 `library_owned_works`，导致生成详情摘要时重新读 DB 又变成 0。
- 在写入当前社团 `CircleWork` 的同一事务里，把本轮库存索引已经确认的本地拥有态同步 upsert 到 `library_owned_works`，确保首次索引完成后详情页立即显示已满足数量。
- 补充当前索引批次拥有态 upsert 的回归断言，覆盖 owned 路径、关联 RJ、大小、文件数和字幕态。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py tests\test_circle_completion_owned_sync.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -` 执行当前索引批次拥有态 upsert 最小断言：通过，确认 `local_owned=True` 的聚合项会写入 `LibraryOwnedWork`。
### Notes
- `backend/app/core/circle_completion_service.py`：新增当前索引批次本地拥有态落库 helper，并在写入社团索引事务中调用。
- `backend/tests/test_circle_completion_owned_sync.py`：新增当前索引批次本地拥有态 upsert 回归断言。
- `progress.md`：追加本轮新社团首次索引后本地命中未落库修复记录。
- 回滚方式：还原上述两个代码 / 测试文件中本轮关于 `_upsert_library_owned_rows_from_items()` 和索引写入事务调用的改动；删除本轮新增的 `progress.md` 段落。

## 2026-06-19 - Task: 修复 Docker 前端静态 chunk 命中旧反代缓存
### What was done
- 排查线上 `kikoerumanager.elena39.xyz:16080` 概览白屏，确认 `/assets/Dashboard-SAGtCc2L.js` 直连应用端口 200，但经 NPM/openresty 不带查询参数时返回 504，带查询参数可正常 200。
- Docker 发版构建将 `KIKOERUMANAGER_VERSION` 传入前端构建阶段，Vite 在正式版本构建时给 JS、CSS 和其它静态资源文件名增加版本前缀，避免不同版本复用同一个 chunk URL 命中坏缓存。
- README 和产品介绍中的 Docker 示例不再写死旧 `1.6.25`，改为 `<版本号>`，并补充静态文件版本戳说明。
### Testing
- `cd frontend && $env:KIKOERUMANAGER_VERSION='v1.6.50'; npm run build`：通过。Vite 输出 `assets/v1.6.50-Dashboard-73wuH8Y3.js` 等版本化文件名，仅保留既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `Select-String frontend\dist\index.html -Pattern "assets/v1\.6\.50"` + 检查 `frontend\dist\assets\v1.6.50-Dashboard-*`：通过，确认入口 HTML 和 Dashboard chunk 都带版本前缀。
### Notes
- `Dockerfile`：将 `KIKOERUMANAGER_VERSION` 提前声明并传入前端构建阶段。
- `frontend/vite.config.js`：根据 `KIKOERUMANAGER_VERSION` / `APP_VERSION` 为构建产物文件名增加版本前缀，本地 dev / dev 构建保持原文件名。
- `README.md`：Docker 部署示例改用 `<版本号>` 并说明版本化静态文件。
- `docs/INTRODUCTION.md`：同步 Docker 镜像版本写法和反代缓存说明。
- `progress.md`：追加本轮 Docker 静态 chunk 缓存修复记录。
- 回滚方式：还原上述文件中本轮关于 `KIKOERUMANAGER_VERSION` 前端构建传递、Vite 文件名前缀和文档说明的改动；删除本段进度记录。线上临时恢复仍可通过重启 NPM 或清理 `/data/nginx/cache` 完成。

## 2026-06-19 - Task: 修复 HTTP 下载预览平台行勾选框错位
### What was done
- 修复 HTTP 外链下载预览树中平台分组行在全部解析失败时错误参与勾选态的问题。
- 平台分组行现在始终不渲染勾选框，也不进入选中高亮计算，避免勾选框与平台图标抢占同一列导致视觉错乱。
- 文件行、失败文件禁用勾选框和目录批量勾选逻辑保持原行为。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `frontend/src/components/asmr/HttpDownloadPanel.vue`：调整 HTTP 下载预览树的勾选态判断，平台分组行直接排除在选择控件和选中态之外。
- `progress.md`：追加本轮 HTTP 下载预览勾选框错位修复记录。
- 回滚方式：还原 `frontend/src/components/asmr/HttpDownloadPanel.vue` 中本轮对 `rowCanShowSelectionCheck()` 和 `previewTreeSelectionClass()` 的改动；删除本段进度记录。

## 2026-06-19 - Task: 修复 API 重命名元数据失败回归与批量性能
### What was done
- API 重命名在 DLsite 失败或只拿到最小降级元数据时直接跳过，单条返回 `422`，批量项标记失败 / skipped，不再生成 `[][RJxxxx]` 或 RJ-only 坏目录名。
- 单条 API 重命名默认复用有效缓存，只有显式 `force_refresh` 才删除缓存；主元数据无效时不会继续请求日语元数据。
- DLsite 元数据和 HTTP 请求增加 45 秒短熔断，HTTP 请求默认并发降到 3，并避免单个失败请求主动关闭共享 `httpx.AsyncClient`。
- 库存页批量 API 重命名改为调用后端 `/api/library/batch-api-rename`，由后端统一限流、计划和汇总结果。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app/api/routes.py app/core/metadata_service.py app/core/dlsite_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_library_browser_api.py -q -k "api_rename"`：通过，3 passed。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_library_browser_api.py -q`：未全绿；3 个既有库存浏览 / 索引用例失败（`test_library_browser_endpoints_support_multi_library`、`test_local_inventory_reads_prefer_usable_index_snapshot`、`test_list_files_coalesces_identical_inflight_requests`），失败点不在本轮 API 重命名路径。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `backend/app/api/routes.py`：API 重命名增加元数据可用性保护、跳过原因日志、缓存强刷开关、批量计划限流和批量跳过结果。
- `backend/app/core/metadata_service.py`：元数据结果增加 `metadata_source` / `dlsite_circuit_open`，最小元数据不再写缓存，并加入 DLsite 元数据短熔断。
- `backend/app/core/dlsite_service.py`：DLsite HTTP 默认并发降到 3，新增短熔断，并避免失败请求关闭共享客户端。
- `backend/tests/test_library_browser_api.py`：新增单条和批量 API 重命名遇到最小元数据时不执行 rename 的回归测试。
- `frontend/src/views/Library.vue`：批量 API 重命名改为按库调用后端批量接口，成功项才刷新路径，失败项保留原路径和原因。
- `docs/TESTING.md`：补充 API 重命名元数据失败、批量接口和缓存复用的回归验证说明。
- `progress.md`：追加本轮 API 重命名性能与结果保护修复记录。
- 回滚方式：还原上述文件中本轮关于 API 重命名元数据保护、DLsite 短熔断、批量接口调用、测试和文档说明的改动；由于工作区已有其他未提交改动，回滚时按相关 hunk 精准还原，不要覆盖社团补全、HTTP 下载预览等非本轮内容。

## 2026-06-19 - Task: 优化社团补全分页加载与封面调度
### What was done
- 新增社团补全摘要、作品分页和当前筛选结果编号接口，把详情页从一次性全量作品响应拆成 summary + 当前 tab 当前页。
- 后端分页读路径复用库存索引、社团作品、关联 RJ、本地拥有态和缓存元数据，普通 missing / owned 列表不再返回 `owned_paths`、完整 `source_compare` 等重字段，compare tab 改为扁平来源对比 DTO。
- 前端 `CircleCompletion.vue` 改为按 tab / 筛选 / 搜索 / 排序 / 分页请求当前页；邻近社团预取只缓存 summary + missing 首屏，并保留分页元信息；全选改走 `work-codes`，继续选中当前筛选结果全部作品。
- `CircleWorksViewport` 增加服务端分页模式和图片加载队列，`WorkCard` / `WorkListRow` 只有可见 / overscan 内作品才挂真实图片 `src`，同屏并发限制为 6。
- 补充新分页接口说明文档和后端分页回归测试。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py app\api\routes.py tests\test_circle_completion_paged_view.py`：通过。
- `cd backend && $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1`：通过，3 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出已有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `backend/app/api/routes.py`：新增 `/summary`、`/works`、`/work-codes` 三个社团补全读接口，并放在 legacy 动态详情路由之前。
- `backend/app/core/circle_completion_service.py`：新增分页视图构造、筛选、排序、summary、work-codes 和轻量 DTO 逻辑，保留旧全量详情接口。
- `backend/tests/test_circle_completion_paged_view.py`：新增 summary 与 legacy 统计一致、missing 分页 / include_dl_only、work-codes、compare 扁平 payload 回归测试。
- `frontend/src/api/index.js`：新增 `getCircleSummary()`、`getCircleWorks()`、`getCircleWorkCodes()`。
- `frontend/src/views/CircleCompletion.vue`：社团补全页面改为 summary + 当前页状态模型，筛选 / 搜索 / 排序 / 分页走服务端请求，全选走编号接口。
- `frontend/src/components/circle/CircleWorksViewport.vue`：增加服务端分页、可见图片激活和 6 并发图片加载队列。
- `frontend/src/components/circle/WorkCard.vue`：增加 `imageActive` 和图片加载完成事件，未激活时只渲染占位。
- `frontend/src/components/circle/WorkListRow.vue`：增加 `imageActive` 和图片加载完成事件，未激活时只渲染占位。
- `docs/circle-completion-paged-loading.md`：记录新接口契约、前端数据流和图片加载策略。
- `progress.md`：追加本轮社团补全加载优化记录。
- 回滚方式：按上述文件中本轮关于社团补全分页接口、前端分页状态、图片队列、新测试和文档的 hunk 精准还原；旧 `GET /api/circle-completion/circles/{circle_id}` 未删除，回滚前端后仍可走旧全量详情接口。

## 2026-06-19 - Task: 修复字幕补配工作台待配对状态按钮褪色
### What was done
- 将字幕补配工作台的等待人工筛选 / 配对状态从处理中蓝色信息态拆出，改为独立 warning 状态。
- 为浅色和暗色模式分别补充更高对比度的琥珀色状态胶囊，避免“待筛选与配对”在暗色工作台里发灰发淡。
- 保留处理中任务的蓝色状态，不改变后端任务状态和任务流。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `frontend/src/components/library/subtitle-workbench/SubtitleTaskStage.vue`：拆分待人工配对状态的状态 class，并新增 `is-warning` 状态胶囊明暗色样式。
- `progress.md`：追加本轮字幕补配工作台状态按钮样式修复记录。
- 回滚方式：还原 `frontend/src/components/library/subtitle-workbench/SubtitleTaskStage.vue` 中本轮对 `statusPillClass()` 和 `.subtitle-active-status-pill.is-warning` 的改动；删除本段进度记录。

## 2026-06-19 - Task: 修复翻译作入库绕过字幕补配
### What was done
- 字幕补配预检恢复使用 Kikoeru 判定原作是否已收录、是否已有字幕、查询是否可靠，避免 ready 库存索引库 ID / 快照漂移时把翻译作误判为新作。
- 库存索引仍用于定位实际候选目录；Kikoeru 命中原作但索引暂未定位到目录时，任务进入字幕补配待处理，不再直接解压入库。
- Kikoeru 查询不稳定时不自动降级普通解压，保留稍后重试提示，避免把可补配字幕源误入库。
- 修正 Kikoeru `total_track_count=0` 被当作未查的问题，空壳原作会被识别并阻止补配入队。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\linked_subtitle_import_service.py tests\test_linked_subtitle_import_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_linked_subtitle_import_service.py -q`：通过，13 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/core/linked_subtitle_import_service.py`：字幕补配预检恢复 Kikoeru 拥有态 / 字幕态判定，ready 库存索引只保留为候选目录定位，并修正空壳 tracks 计数判断。
- `backend/tests/test_linked_subtitle_import_service.py`：新增 Kikoeru 命中原作但索引未命中时不得按新作入库、以及 Kikoeru 空壳作品拦截的回归测试。
- `docs/TESTING.md`：新增字幕补配 Kikoeru 回归验证说明和推荐测试命令。
- `progress.md`：追加本轮翻译作绕过字幕补配修复记录。
- 回滚方式：按上述文件中本轮关于 Kikoeru 字幕补配判定、空壳计数、测试与文档说明的 hunk 精准还原；不要回退工作区已有社团补全、API 重命名、HTTP 下载和字幕工作台样式等非本轮改动。

## 2026-06-19 - Task: 修复无字幕翻译作绕过关联重复入库
### What was done
- 根据 13:41 的 `RJ01625472.zip` 实测日志确认：任务已查到 `RJ01625472 -> RJ01609723` 且 Kikoeru 命中原作缺字幕，但因为压缩包内无字幕，字幕补配未入队；随后普通关联重复又被过宽条件跳过，最终直接入库。
- 收紧普通查重跳过条件：只有预检结果确认可进入字幕补配待处理 / 执行时，翻译作命中原作才允许跳过普通关联重复。
- 自动处理预检新增拦截：翻译作命中 Kikoeru 原作但来源压缩包没有可补配字幕时，直接写入问题作品并把任务置为 `waiting_manual`，不再继续解压入库。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\task_engine.py app\core\classifier.py app\core\linked_subtitle_import_service.py tests\test_linked_subtitle_import_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_linked_subtitle_import_service.py -q`：通过，15 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/core/classifier.py`：普通关联重复跳过逻辑增加 `can_stage_pending` / `should_queue_pending` / `can_execute` 资格判断。
- `backend/app/core/task_engine.py`：自动处理预检在普通查重前拦截无字幕翻译作，写入 `LINKED_WORK` 问题作品并停止入库。
- `backend/tests/test_linked_subtitle_import_service.py`：新增无字幕翻译作不得跳过关联重复、任务预检应拦截无字幕翻译作的回归测试。
- `docs/TESTING.md`：补充无字幕翻译作压缩包不能直接入库的回归验证点。
- `progress.md`：追加本轮无字幕翻译作绕过关联重复入库修复记录。
- 回滚方式：按上述文件中本轮关于无字幕翻译作拦截、普通查重跳过条件、测试与文档说明的 hunk 精准还原；不要回退工作区已有社团补全、API 重命名、HTTP 下载和前一轮 Kikoeru 补配判定改动。

## 2026-06-19 - Task: 优化社团索引启动卡顿与进度刷新
### What was done
- 通过服务器 `\\Elena\docker\prekikoeru\data\app.log` 确认 13:10 左右任务 `0a65190e-4dcb-4b41-9012-ed681e5425ff` 从 `13:10:09 同步本地拥有态索引 (5%)` 卡到 `13:11:31 收集本地社团候选 (12%)`，重复任务也有约 83 秒同类卡顿；瓶颈是单社团索引入口同步等待 `sync_local_owned_index()` 全量重建。
- 社团索引入口移除全量本地拥有态同步等待，改为直接进入当前社团索引；当前社团拥有态继续在后段通过 ready 库存索引局部核对并写回 `LibraryOwnedWork`。
- 局部拥有态写回增加 ready 索引保护：索引可用时只清理当前社团本次涉及但未命中的 canonical 快照；索引不可用时不清旧快照，避免误删拥有态。
- 前端社团索引进度改为 SSE 主通道：启动后不再立即轮询 job 状态，运行中耗时本地每秒递增；当前 job 超过 45 秒没有收到 SSE 事件或终态收尾时才低频兜底查询。
- 修复社团补全完成通知里的 `_format_circle_search_efficiency` 未定义错误，避免索引完成后通知构建抛 `NameError`。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py app\core\notification_helper.py app\api\routes.py tests\test_circle_completion_owned_sync.py`：通过。
- `cd backend && $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q --maxfail=1`：通过，4 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd backend && $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py tests\test_circle_completion_owned_sync.py -q --maxfail=1`：通过，7 passed；仅有既有 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `backend/app/core/circle_completion_service.py`：移除单社团索引入口的全量本地拥有态同步等待，局部 owned 写回支持 ready 索引保护和当前 canonical prune。
- `backend/app/core/notification_helper.py`：补齐社团补全通知统计里的搜索效率格式化函数。
- `backend/tests/test_circle_completion_owned_sync.py`：新增 ready 索引不可用不清快照、当前 canonical 未命中时局部 prune 的回归测试。
- `frontend/src/views/CircleCompletion.vue`：索引任务进度改为 SSE 主通道、本地计时器和断线兜底状态查询。
- `docs/circle-completion-paged-loading.md`：补充索引任务拥有态同步、SSE 进度通道和验证入口说明。
- `progress.md`：追加本轮社团索引启动卡顿与进度刷新修复记录。
- 回滚方式：按上述文件中本轮关于跳过全量 owned 同步、局部 owned prune、SSE 进度兜底、通知搜索效率函数、测试和文档说明的 hunk 精准还原；不要回退工作区已有社团补全分页、字幕补配、API 重命名等非本轮改动。

## 2026-06-19 - Task: 修复字幕补配工作台完成态胶囊发白
### What was done
- 仅针对当前任务日志面板右上角的“已完成补配 / 已匹配完成”状态胶囊增加专用完成态 class。
- 完成补配状态在浅色和暗色模式下改为高对比实心绿色，避免沿用普通 success 淡色样式导致文字像褪色发白。
- 其它成功态、等待态、处理中状态和日志正文不变。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `frontend/src/components/library/subtitle-workbench/SubtitleTaskStage.vue`：当前任务顶部状态胶囊在 `manual_match_completed` 时追加 `is-manual-completed`，并补充专用明暗色样式。
- `progress.md`：追加本轮字幕补配完成态胶囊样式修复记录。
- 回滚方式：还原 `frontend/src/components/library/subtitle-workbench/SubtitleTaskStage.vue` 中本轮对顶部状态胶囊 class 绑定和 `.is-manual-completed` 样式的改动；删除本段进度记录。

## 2026-06-19 - Task: 增加社团补全 RJ 定位搜索
### What was done
- 新增社团补全作品反查接口，可按 RJ、关联 RJ、作品标题或社团名在已建立索引内定位作品所属社团，不触发 DLsite / Kikoeru 外部请求。
- 社团补全左侧目录新增“按 RJ 定位作品”搜索框，输入 RJ 后展示命中作品、所属社团、封面和收录 / 可下载状态。
- 点击搜索结果会把目标社团带入左侧目录，切到来源对比 tab，并用命中 RJ 过滤当前社团作品列表，保证已收录和缺失作品都能直接定位。
- 补充关联 RJ 命中 canonical 作品的后端回归测试和接口文档。
### Testing
- `cd backend && venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py app\api\routes.py`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1 --basetemp=.pytest-codex-circle-rj-search`：通过，4 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- backend/app/api/routes.py backend/app/core/circle_completion_service.py backend/tests/test_circle_completion_paged_view.py frontend/src/api/index.js frontend/src/views/CircleCompletion.vue`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/api/routes.py`：新增 `/api/circle-completion/work-search` 路由，并加入慢请求上下文。
- `backend/app/core/circle_completion_service.py`：新增本地索引作品反查方法，匹配 canonical、display、linked RJ、标题和社团信息。
- `backend/tests/test_circle_completion_paged_view.py`：新增 RJ / linked RJ 定位所属社团的回归测试。
- `frontend/src/api/index.js`：新增 `circleCompletionApi.searchWorks()`。
- `frontend/src/views/CircleCompletion.vue`：新增左侧 RJ 定位搜索 UI、debounce / AbortController、跳转到目标社团 compare tab 的交互逻辑和样式。
- `docs/circle-completion-paged-loading.md`：补充作品反查接口契约和前端数据流说明。
- `progress.md`：追加本轮社团补全 RJ 定位搜索记录。
- 回滚方式：按上述文件中本轮关于 `work-search` 接口、RJ 定位搜索 UI / 状态逻辑、测试和文档说明的 hunk 精准还原；不要回退工作区已有字幕补配、社团索引性能和分页加载等非本轮改动。

## 2026-06-19 - Task: 调整社团补全页头搜索与索引入口
### What was done
- 将社团补全 RJ / 作品定位搜索从左侧目录移动到页头搜索框，匹配截图里的顶栏位置。
- 页头搜索命中后会保留搜索 RJ，跳到目标社团的来源对比 tab，并用该 RJ 过滤作品列表；无命中时在页头下拉里显示 `No Data`。
- 移除左侧 RJ 定位搜索框和对应样式，避免出现两个同类搜索入口。
- 将“建立 / 刷新索引”和“批量创建”合并为页头一个“批量建立 / 刷新”按钮，点击后统一弹出单个 / 批量社团名输入框。
### Testing
- `cd backend && venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py app\api\routes.py`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1 --basetemp=.pytest-codex-circle-rj-search-hero`：通过，4 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `frontend/src/views/CircleCompletion.vue`：页头搜索框接入作品定位结果下拉、No Data 状态、RJ 保留和跳转过滤逻辑，并合并索引创建入口弹框。
- `docs/circle-completion-paged-loading.md`：将作品反查接口说明从左侧定位改为页头定位，并补充 No Data 行为。
- `progress.md`：追加本轮页头搜索与索引入口调整记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 中本轮关于页头搜索框、下拉结果、No Data、索引按钮合并和删除左侧定位入口的 hunk；文档和本段进度记录按对应 hunk 精准还原。

## 2026-06-19 - Task: 修复社团补全原作补配后不计入含字幕
### What was done
- 查服务器日志确认 `RJ01609723` 字幕补配已完成：操作历史对应任务导入 8 个字幕文件，库存索引随后扫描到 `/subtitles` 子树 `files=8`，问题不在补配落盘。
- 定位到社团补全把“未收录时优先展示 / 下载翻译作”的 `preferred_variant` 口径泄漏到了已收录态 `owned_variant`，导致原作目录已补配字幕时没有命中“原作含字幕”条件。
- 新增已收录主版本选择逻辑：仅当本地字幕目录或主目录真实路径明确落在 canonical 原作 RJ 下时，社团补全展示、统计和筛选才按原作版本计算；未收录作品仍保持简中 / 繁中优先展示与下载。
- 分页接口和旧详情接口同时接入同一选择逻辑，避免社团补全不同读路径出现“一个显示有字幕、一个不显示”的口径漂移。
- 新增 `RJ01609723 -> RJ01625472/RJ01625473` 关联链回归测试，覆盖“含字幕”统计、已收录字幕筛选、旧详情 payload，以及未收录作品仍优先翻译作展示 / 下载。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py tests\test_circle_completion_paged_view.py`：通过。
- `cd backend && $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1 --basetemp=$env:TEMP\km-circle-subtitle-paged`：通过，6 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/core/circle_completion_service.py`：新增 `_pick_owned_primary_rjcode()`，并在分页视图与旧详情视图构造 `owned_variant` 时使用真实字幕目录 / 主目录路径优先确认原作字幕状态。
- `backend/tests/test_circle_completion_paged_view.py`：新增原作目录已有字幕但关联链含简中 / 繁中版本时仍计入 `owned_stats.subtitle` 的回归测试，并补充未收录作品仍保持翻译作优先的保护测试。
- `progress.md`：追加本轮服务器日志调查与社团补全字幕状态修复记录。
- 回滚方式：还原 `backend/app/core/circle_completion_service.py` 中本轮 `_pick_owned_primary_rjcode()` 及两处调用 hunk；还原 `backend/tests/test_circle_completion_paged_view.py` 中新增的原作字幕状态回归测试；删除本段进度记录。

## 2026-06-19 - Task: 优化社团补全 RJ 搜索跳转定位
### What was done
- 页头 RJ / 作品搜索结果点击后不再跳到来源对比 tab，而是按作品收录态跳到 `已满足` 或 `缺失作品`。
- 新增轻量作品定位接口，只返回命中页码、canonical 和分页信息，不回传全量作品或全量 RJ codes，避免大社团点击搜索结果时产生额外卡顿。
- 跳转时会清理会隐藏目标作品的临时筛选条件，翻到命中页后给对应卡片 / 列表行播放定位高亮特效。
- 跳转流程改为延迟加载目标社团，先算页码再请求目标页，避免先加载第一页再二次跳页导致闪烁和重复请求。
### Testing
- `cd backend && venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py app\api\routes.py`：通过。
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1 --basetemp=.pytest-codex-circle-rj-location`：通过，6 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- backend/app/api/routes.py backend/app/core/circle_completion_service.py backend/tests/test_circle_completion_paged_view.py docs/circle-completion-paged-loading.md frontend/src/api/index.js frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue frontend/src/views/CircleCompletion.vue progress.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/api/routes.py`：新增 `/api/circle-completion/circles/{circle_id}/work-location` 轻量定位路由。
- `backend/app/core/circle_completion_service.py`：新增 RJ 候选匹配与定位页码计算逻辑，复用分页 tab / 筛选 / 排序口径。
- `backend/tests/test_circle_completion_paged_view.py`：补充缺失 / 已满足作品定位页码回归断言。
- `frontend/src/api/index.js`：新增 `circleCompletionApi.getCircleWorkLocation()`。
- `frontend/src/views/CircleCompletion.vue`：搜索跳转改为按 owned 状态进入已满足 / 缺失、翻到目标页并触发定位高亮；跳转期间抑制重复列表请求。
- `frontend/src/components/circle/CircleWorksViewport.vue`：透传搜索定位高亮状态到卡片和列表行。
- `frontend/src/components/circle/WorkCard.vue`、`frontend/src/components/circle/WorkListRow.vue`：新增搜索定位高亮动效。
- `docs/circle-completion-paged-loading.md`：记录 `work-location` 接口契约和页头搜索跳转性能约束。
- `progress.md`：追加本轮社团补全 RJ 搜索跳转定位记录。
- 回滚方式：还原上述文件中本轮关于 `work-location`、`locatedCodes` / `locateFlash`、搜索跳转分页定位和文档记录的 hunk；不要回退工作区已有分页加载、页头搜索、字幕补配等非本轮改动。

## 2026-06-19 - Task: 优化社团补全搜索定位提示文案
### What was done
- 将页头 RJ 搜索定位成功 toast 从“已跳到 已满足”改为更自然的“已定位到 RJxxxx · 已满足作品 / 缺失作品 · 第 N 页”。
- 将定位异常提示改为“已打开某类作品，但没有在当前结果中找到 RJxxxx”，避免出现生硬的 tab 名拼接。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- frontend/src/views/CircleCompletion.vue progress.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `frontend/src/views/CircleCompletion.vue`：优化搜索定位成功和未命中提示文案。
- `progress.md`：追加本轮 toast 文案优化记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 中本轮两条 `ElMessage` 文案 hunk，并删除本段进度记录。

## 2026-06-19 - Task: 精简社团补全定位提示
### What was done
- 将社团补全页头搜索定位 toast 进一步精简：成功只显示 `已找到`，未命中只显示 `未找到`。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- frontend/src/views/CircleCompletion.vue progress.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `frontend/src/views/CircleCompletion.vue`：精简搜索定位成功 / 未命中提示文案。
- `progress.md`：追加本轮提示文案精简记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 中本轮两条 `ElMessage` 文案 hunk，并删除本段进度记录。

## 2026-06-19 - Task: 修复百度网盘同时下载文件数按批次生效
### What was done
- 将百度网盘“同时下载文件数”改为服务级全局下载槽，所有百度下载任务共享同一个文件并发上限。
- 每个 BaiduPCS-Go 子进程只下载 1 个文件，实际文件并发由后端全局槽控制，避免多个下载批次各自开满配置上限。
- 全局槽会读取当前配置和 `resource_budget.network_download`，配置调小后新文件会等待已有下载释放。
- 设置页文案改为“全局同时下载文件数”，并同步产品说明。
### Testing
- `cd backend && ..\backend\venv\Scripts\python.exe -m pytest tests\test_baidu_netdisk_service.py -q`：通过，44 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd backend && ..\backend\venv\Scripts\python.exe -m py_compile app\core\baidu_netdisk_service.py tests\test_baidu_netdisk_service.py`：通过。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- backend/app/core/baidu_netdisk_service.py backend/tests/test_baidu_netdisk_service.py frontend/src/components/settings/BaiduNetdiskSettingsPanel.vue`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/core/baidu_netdisk_service.py`：新增服务级百度下载槽，下载行进入 BaiduPCS-Go 前必须占用全局槽，PCS-Go 下载参数收敛为单文件。
- `backend/tests/test_baidu_netdisk_service.py`：新增跨任务全局下载槽回归测试，并更新 PCS-Go `-l 1` 参数断言。
- `frontend/src/components/settings/BaiduNetdiskSettingsPanel.vue`：将设置项标题和提示改为全局共享语义。
- `docs/INTRODUCTION.md`：补充百度网盘全局同时下载文件数说明。
- `progress.md`：追加本轮百度网盘全局并发修复记录。
- 回滚方式：还原上述文件中本轮关于 `_acquire_global_download_slot()`、PCS-Go `-max_download_load/-l` 单文件化、全局并发测试、设置文案和文档说明的 hunk；不要回退工作区已有社团补全和字幕相关改动。

## 2026-06-19 - Task: 固定库存分页大小并优化社团聚合分页卡顿
### What was done
- 库存页普通目录、社团根目录、社团作品列表统一使用同一个分页大小偏好；用户选 10 / 20 / 50 / 100 后会一直保持，切目录或切社团视图不再自动回到 50/page。
- 调查 `data/app.log` 确认历史卡顿集中在 `/api/library/circle-browser/files`：2026-06-18 00:16-00:24 左右连续慢请求，单次约 1.4-3.4s，query 基本为 `page_size=50`。
- 社团聚合 snapshot 缓存从 30 秒延长到 5 分钟，并加构建锁；连续分页 / 切组不会多个请求同时重算全量 `library_index_entries` 聚合。
- 社团根和社团作品列表路由改为在线程池执行同步 DB 聚合，避免一次重聚合卡住 FastAPI event loop，把其他 API / SSE 一起拖慢。
- 修复翻译作子目录社团识别：`[社团][原作RJ]/翻译RJ` 这类路径会继承最近的括号父层社团名，减少不该进入“未识别社团”的作品。
- 分页当前页样式改为更明显的选中态：当前页会轻微上浮放大，浅色 / 暗色都有更强边框和阴影。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\core\library_circle_aggregation_service.py app\api\routes.py`：通过。
- `cd backend && $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_library_circle_aggregation.py tests\test_library_circle_aggregation_service.py -q --maxfail=1 --basetemp=$env:TEMP\km-library-circle-pagination`：通过，14 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- frontend/src/views/Library.vue frontend/src/index.css frontend/src/dark-mode.css backend/app/core/library_circle_aggregation_service.py backend/app/api/routes.py`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `frontend/src/views/Library.vue`：统一目录 / 社团分页大小状态，切换社团和目录时不再重置到 50。
- `frontend/src/index.css`：增强 `.km-pagination-wrap` 当前页选中态，加入轻微放大和更明显阴影。
- `frontend/src/dark-mode.css`：补暗色库存分页当前页选中态，压住暗黑兜底规则。
- `backend/app/core/library_circle_aggregation_service.py`：延长 snapshot TTL、加构建锁、增加同步列表入口，并修复翻译作子目录社团识别。
- `backend/app/api/routes.py`：社团聚合列表接口和社团浏览列表路径改为 `asyncio.to_thread` 执行，避免同步聚合阻塞事件循环。
- `progress.md`：追加本轮库存分页与社团聚合性能修复记录。
- 回滚方式：还原上述文件中本轮关于 `initialLibraryPageSize` / `syncLibraryPageSizePreference`、`.km-pagination-wrap` active 样式、`_SNAPSHOT_TTL_SECONDS` / `_snapshot_lock` / `browse_circle_listing` / 父层括号社团识别、以及 `asyncio.to_thread` 路由调用的 hunk；删除本段进度记录。

## 2026-06-19 - Task: 修复 Gofile 任务详情文件树显示公共下载根
### What was done
- 禁止 HTTP/Gofile 任务详情用 `final_output_path` / `download_root` 扫描公共下载根目录生成 `file_tree_items`，避免把 `.aria2-rpc`、百度临时目录和其它下载会话显示成当前 Gofile 任务文件。
- 保留任务详情前端从 `download_files` 构造文件列表的路径，因此当前任务仍显示自己的下载文件行，不再混入下载根下的无关目录。
- 任务中心文件树缓存签名增加 `domain` / `kind` / `status`，避免详情切换或状态更新时复用过旧树结果。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app/core/task_center_service.py`：通过。
- `cd backend && <inline python with .\venv\Scripts\python.exe>`：通过；构造公共下载根含 `.aria2-rpc` / `other-gofile-session`，序列化 Gofile detail 后确认 metadata 不生成 `file_tree_items`，且不包含这些无关目录。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_task_center_service.py -q --basetemp .pytest-codex-task-center-tree`：未完全通过，6 passed / 4 failed；失败集中在既有 mock 非 awaitable 和物化删除断言，非本轮 Gofile 文件树修复断言。
- `git diff --check -- backend/app/core/task_center_service.py frontend/src/views/Tasks.vue progress.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/core/task_center_service.py`：HTTP 下载详情模式跳过目录快照回填，避免公共下载根被当成当前任务产物树。
- `frontend/src/views/Tasks.vue`：文件树缓存签名纳入任务域、类型和状态。
- `progress.md`：追加本轮 Gofile 任务详情文件树修复记录。
- 回滚方式：还原上述两个代码文件中本轮关于 `_should_skip_directory_file_tree_snapshot()` / `_ensure_file_tree_metadata(..., domain)`、以及 `buildFileTreeCacheSignature()` 新增签名字段的 hunk；删除本段进度记录。

## 2026-06-20 - Task: 修复百度网盘连续分卷重命名生成重复后缀
### What was done
- 百度网盘预览树对连续分卷批量重命名时，只给每个文件传统一的分卷基名，不再提前把 `.7z.002` / `.zip.003` 这类分卷后缀写进 `custom_name`。
- 后端最终生成下载保存名时增加分卷后缀去重兜底，旧缓存或旧前端 payload 里即使传入 `RJ01618696.7z.002`，也不会再拼成 `RJ01618696.7z.002.7z.002`。
- 覆盖“每卷 custom_name 带自己的分卷号”和“所有卷误套首卷全名”两类回归场景。
### Testing
- `cd backend && ..\backend\venv\Scripts\python.exe -m pytest tests\test_baidu_netdisk_service.py -q --basetemp=$env:TEMP\pytest-baidu-netdisk-volume-name`：通过，46 passed；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
### Notes
- `frontend/src/components/asmr/HttpDownloadPanel.vue`：百度连续分卷自定义命名统一只传基名，分卷后缀由后端按原始文件补回。
- `backend/app/core/baidu_netdisk_service.py`：新增 `_dedupe_custom_archive_volume_name()`，在保存名落地前清理重复或误套的分卷后缀。
- `backend/tests/test_baidu_netdisk_service.py`：新增百度分卷重复后缀和首卷名误套全部分卷的回归测试。
- `progress.md`：追加本轮百度网盘连续分卷重命名修复记录。
- 回滚方式：还原上述三个代码文件中本轮关于 `baiduVolumeFileCustomName()`、`_dedupe_custom_archive_volume_name()`、新增两个测试用例的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 修复大分卷缺正确密码时反复完整解压
### What was done
- 重新核查服务器日志，确认 `RJ01618696.7z.001` 是 4 分卷有密码大包，正确密码缺失于密码库；旧逻辑在轻量探测 `unknown` 后会把多个候选逐个升级为完整 `7zz x`，每个候选都要跑到 CRC 失败才切下一个，看起来像无限循环并长期占用 `archive_cpu`。
- 为 1GB 以上大包增加 unknown 探测完整解压兜底上限，默认最多 3 个候选进入完整解压，后续 unknown 候选直接跳过并尽快定性为 `wrong_password`，让任务进入问题作品而不是继续消耗解压槽。
- 取消等待解压槽位期间的任务后，拿到槽位会再次检查取消状态，不再额外启动一次 7z 子进程。
- 解压阶段返回空结果且不是用户取消时，写入问题作品后立即把任务状态收口到 `WAITING_MANUAL`，避免任务中心继续显示 processing。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_extract_service.py tests/test_task_engine.py -k "large_archive_caps_unknown_probe_full_extracts or manual_retry_skips_no_password_full_extract_when_probe_unknown or auto_process_extract_failure_moves_to_waiting_manual" --basetemp=.pytest-tmp-rj01618696-loop -q`：通过，3 passed / 172 deselected；仅有既有 deprecation warnings 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/core/extract_service.py`：新增大包 unknown 探测完整解压上限，并在 7z 槽位获取后再次拦截已取消任务。
- `backend/app/core/task_engine.py`：解压失败写入问题作品后立即切到 `WAITING_MANUAL`。
- `backend/tests/test_extract_service.py`：新增大分卷缺正确密码时限制完整解压候选数的回归测试。
- `backend/tests/test_task_engine.py`：新增解压失败后任务状态收口到等待人工的回归测试。
- `progress.md`：追加本轮 RJ01618696 大分卷缺密码卡槽修复记录。
- 回滚方式：还原上述代码文件中本轮关于 `UNKNOWN_PROBE_*`、取消后不启动 7z、解压失败 WAITING_MANUAL 收口及新增测试的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 修复解压进度控制字符乱码与文件名密码优先级
### What was done
- 重新核查 `RJ01618696(southplus@adark).7z.001` 运行日志，确认截图底部 `Open□□□□` 不是文件名编码乱码，而是 7z 进度流里的退格控制字符被解析成“当前文件”后展示出来。
- 解压进度解析现在会过滤 ANSI / 退格等终端控制字符，并拒绝把 `Open` 这类 7z 状态词当作当前文件名；日志页也加了旧进度日志展示兜底。
- 密码候选顺序调整为密码库 / 文件名嗅探优先于 RJ 号猜测，避免大包 unknown 兜底上限被 `RJ` / `RJ+1` / `RJ-1` 先耗掉，导致文件名里的真实密码还没轮到就被跳过。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m pytest tests/test_extract_service.py tests/test_task_engine.py -k "filename_password_sniff_reads_split_archive_name or extract_7z_progress_ignores_terminal_control_open or large_archive_tries_sniffed_password_before_rj_guess or large_archive_caps_unknown_probe_full_extracts or manual_retry_skips_no_password_full_extract_when_probe_unknown or auto_process_extract_failure_moves_to_waiting_manual" --basetemp=.pytest-tmp-rj01618696-garbled-full -q`：通过，6 passed / 172 deselected；仅有既有 deprecation warnings 和 `.pytest_cache` 写入 warning。
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `git diff --check -- backend/app/core/extract_service.py backend/app/core/task_engine.py backend/tests/test_extract_service.py frontend/src/views/Logs.vue progress.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/core/extract_service.py`：清洗 7z 进度控制字符、过滤 `Open` 状态词，并把密码库 / 文件名嗅探候选排在 RJ 猜测密码前。
- `frontend/src/views/Logs.vue`：日志页解析解压进度详情时清理控制字符，旧日志中 `Open` 状态不再显示为当前文件。
- `backend/tests/test_extract_service.py`：新增分卷文件名嗅探密码、7z 控制字符过滤、以及大包优先尝试文件名密码的回归测试。
- `progress.md`：追加本轮解压进度乱码与密码候选顺序修复记录。
- 回滚方式：还原上述代码文件中本轮关于 `_strip_terminal_control_text`、`_extract_7z_progress_entry_name`、密码候选顺序、`parseExtractProgressDetail` 和新增测试的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 修复 API 重命名 Markdown RJ 与 DLsite 空 fallback
### What was done
- 修复 API 重命名元数据任务的 RJ 锁定逻辑：当任务上下文里混入 `[RJ01649758](...)` 这类展示层 Markdown 链接时，后端会先提取干净 RJ，再请求 DLsite 和写进进度日志。
- 修复 DLsite `get_product_info()` 的页面 fallback 空返回处理：translation fallback 返回 `None` 时按空结果收口，不再触发 `'NoneType' object is not subscriptable`。
- 增加回归测试覆盖 Markdown RJ 锁定、API rename 传参归一化，以及 DLsite 空 fallback 返回 `None` 的路径。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q -k "api_rename or metadata_service_normalizes" --basetemp=.pytest-tmp\api-rename-markdown`：通过，5 passed / 16 deselected；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_bonus_detection.py -q --basetemp=.pytest-tmp\dlsite-empty-fallback`：通过，7 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/core/metadata_service.py`：锁定 RJ 先走 `_extract_rjcode()`，避免把 Markdown 链接当成真实 RJ。
- `backend/app/core/dlsite_service.py`：translation page fallback 返回空时兜底为空 dict。
- `backend/tests/test_library_browser_api.py`：新增 API rename 与 MetadataService 的 Markdown RJ 归一化回归测试。
- `backend/tests/test_circle_completion_bonus_detection.py`：新增 DLsite 空 translation fallback 回归测试。
- `progress.md`：追加本轮 API 重命名元数据修复记录。
- 回滚方式：还原上述代码文件中本轮关于 locked RJ 归一化、fallback 空 dict 兜底和新增测试的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 修复库存重命名后名称短暂回跳
### What was done
- 核查服务器日志确认 `RJ01649758` 纯 RJ 请求已经被后端正确识别，但 DLsite 元数据链路仍因短熔断 / SSL EOF / read timeout 降级为 minimal，所以 API 重命名按保护逻辑返回 422 并跳过。
- 修复普通库存重命名和批量重命名接口：默认在返回成功前同步提交库存索引 move，避免文件系统已改名但库存页下一轮走旧索引导致名称短暂变回旧值。
- 保留字幕工作台等显式 `skip_index_mutation=True` 的临时重命名行为，不把临时字幕路径写入库存索引。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\library_manager.py app\core\metadata_service.py app\core\dlsite_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q -k "rename or api_rename or metadata_service_normalizes" --basetemp=.pytest-tmp\rename-index-sync`：通过，13 passed / 10 deselected；仅有既有 SQLAlchemy / FastAPI / pytest-asyncio deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `backend/app/api/routes.py`：普通库存重命名和批量重命名默认传 `sync_index_mutation=not skip_index_mutation`。
- `backend/app/core/library_manager.py`：批量本地 / 远程重命名支持同步索引 move flush。
- `backend/tests/test_library_browser_api.py`：新增默认同步索引与跳过索引场景的路由回归测试，并补批量重命名同步参数断言。
- `progress.md`：追加本轮库存重命名索引同步记录。
- 回滚方式：还原上述代码文件中本轮关于 `sync_index_mutation` 参数传递、批量重命名同步索引 move flush 和新增测试的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 稳定库存重命名后的前端显示
### What was done
- 库存页在重命名成功后记录短期旧路径到新路径映射，后续后台刷新如果仍拿到旧索引结果，会在写入表格前替换成新路径，避免成功后又闪回旧名字。
- 刷新结果里如果旧路径和新路径同时出现，前端会丢弃旧路径行，只保留新名字，减少索引追赶窗口里的重复行。
- API 重命名无变化返回补齐 `path/new_path/new_name`，前端统一按 `new_path || path` 更新当前行。
### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\library_manager.py app\core\metadata_service.py app\core\dlsite_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q -k "api_rename or rename or metadata_service_normalizes" --basetemp=.pytest-tmp\rename-stable-ui`：通过，13 passed / 10 deselected；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
### Notes
- `frontend/src/views/Library.vue`：新增短期重命名路径映射，并在目录 / 社团视图刷新落表前应用映射与去重。
- `backend/app/api/routes.py`：API 重命名无变化返回补齐 `new_path` / `new_name`，批量 no-change 子项补齐 `new_path`。
- `progress.md`：追加本轮前端重命名显示稳定记录。
- 回滚方式：还原上述代码文件中本轮关于 `RECENT_RENAME_TTL_MS`、`recentRenamePathMap`、`applyRecentRenameRows()`、API rename no-change 返回字段和前端 `new_path` 读取的 hunk，并删除本段进度记录。

## 2026-06-20 - Task: 修复 API 重命名 DLsite 空发布日期降级
### What was done
- 核查本机 `data/app.log`，确认 `RJ01649758` 的 API 重命名不是前端失效，而是 DLsite 返回 200 后元数据构造阶段抛出 `'NoneType' object is not subscriptable`，随后降级为 minimal 并按保护逻辑返回 422。
- 复现并定位到 DLsite `product.json` 对该限定图类商品返回 `regist_date: null`，后端直接执行 `product.get('regist_date', '')[:10]` 导致异常。
- 统一收口发布日期字段：DLsite 发布日期为 `null` 时写入空字符串，不再阻断 `maker_name`、封面、价格等有效元数据进入 API 重命名链路。
### Testing
- `cd backend && .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\metadata_service.py app\core\dlsite_service.py`：通过。
- `cd backend && .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q -k "api_rename or metadata_service_normalizes or null_dlsite_release_date" --basetemp=.pytest-tmp\api-rename-null-date`：通过，6 passed / 18 deselected；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
- `cd backend` 后用项目 venv 实际调用 `MetadataService.fetch()` 拉取 `RJ01649758`：通过，返回 `metadata_source=dlsite`、`maker_name=おいしいおこめ`、`release_date=""`、封面 URL 和 `price_text=0円`。
### Notes
- `backend/app/core/metadata_service.py`：新增发布日期空值归一化，并替换 DLsite 主链、直连链和日文元数据链中对 `regist_date` 的直接切片。
- `backend/tests/test_library_browser_api.py`：新增 DLsite `regist_date=None` 时仍能构建有效元数据的回归测试。
- `progress.md`：追加本轮 API 重命名 DLsite 空发布日期修复记录。
- 回滚方式：还原 `backend/app/core/metadata_service.py` 中 `_normalize_release_date` 与三处调用替换，删除 `backend/tests/test_library_browser_api.py` 中 `test_metadata_service_accepts_null_dlsite_release_date`，并删除本段进度记录。

## 2026-06-20 - Task: 整理系统过滤与字幕过滤规则正则
### What was done
- 把系统文件过滤规则里“无 SE/无音效/无射精音/音声のみ”散乱正则，合并为可维护的一条主表达式，并明确保留 mp3 单独拦截。
- 将字幕过滤规则也整理为一条主表达式，保留 `noSE / SEなし / 効果音カット版 / BGMなし / 無射精音 / 反転 / 左右逆 / 不含音效 / mp3` 等语义。

### Testing
- `backend\\venv\\Scripts\\python.exe -c \"import re,yaml; ...\"`：已验证 `backend/config/config.yaml` 与 `data/config/config.yaml`（本机运行配置）中相关规则均可被 `re.compile` 成功解析，无语法错误。

### Notes
- `backend/config/config.yaml`：更新 `filter.rules` 中 `过滤无 SE 的文件` 与 `过滤 MP3 文件` 两条规则；移除重复/散乱的 `过滤无SE文件夹` 规则，统一语义为 `target: all`。
- `data/config/config.yaml`：本地运行配置中同步整理 `filter.rules` 与 `rj_subtitle.subtitle_filter_rules`。
- 回滚方式：还原本轮 `backend/config/config.yaml` 的对应 hunk（以及本地 `data/config/config.yaml` 的同处规则块）即可。

## 2026-06-20 - Task: 收窄 no 关键词匹配边界
### What was done
- 按你的要求去掉系统过滤和字幕过滤里对 `no` 的独立匹配，避免误伤 `n0.1` 这类正常命名。
- 保留 `noSE`、`without` 等更明确的语义项，避免影响有意义的无 SE 过滤场景。

### Testing
- 用项目 venv 复编译 `backend/config/config.yaml` 与 `data/config/config.yaml` 中相关 `pattern`，无语法报错。

### Notes
- `backend/config/config.yaml`：`过滤无 SE 的文件` 规则中移除 `no` 关键词独立匹配项。
- `data/config/config.yaml`：`filter.rules` 与 `rj_subtitle.subtitle_filter_rules` 同步移除独立 `no` 匹配项，保留 `noSE/without` 组合语义。

## 2026-06-21 - Task: 百度网盘下载并发配置生效
### What was done
- 修正 BaiduPCS-Go 下载配置和下载命令，使 `max_download_load` 使用配置值，不再固定写死为 `1`。
- 补充百度网盘下载测试断言，覆盖配置命令与实际下载参数里的 `-l` 值。

### Testing
- `backend\venv\Scripts\python.exe -m pytest backend/tests/test_baidu_netdisk_service.py -q`：在仓库根目录执行时因 `ModuleNotFoundError: No module named 'app'` 失败，属于测试入口路径问题。
- `backend\.venv` 不存在；改用项目现有 `backend\venv`。
- 在 `backend` 目录执行 `.\venv\Scripts\python.exe -m pytest tests\test_baidu_netdisk_service.py -q` 与定点三条百度下载用例时，进程超过 90 秒无输出，已停止；未获得通过结果。

### Notes
- `backend/app/core/baidu_netdisk_service.py`：BaiduPCS-Go 配置命令和下载命令改为读取 `max_download_load`。
- `backend/tests/test_baidu_netdisk_service.py`：更新下载参数断言，并增加不同 `max_download_load` 的覆盖。
- `progress.md`：追加本轮百度网盘下载并发配置记录。
- 回滚方式：还原本轮上述两个百度网盘相关文件的 hunk，并删除本段进度记录。

## 2026-06-21 - Task: 仪表盘最近归档面板布局压缩
### What was done
- 压缩最近归档筛选条和搜索输入高度，减少面板顶部占用。
- 计算分页可容纳行数时改为读取当前页最大行高，并加入安全余量，降低卡片高度差导致的底部溢出风险。

### Testing
- `npm run build`：通过。

### Notes
- `frontend/src/components/dashboard/DashboardArchive.vue`：调整最近归档筛选条尺寸、行高测量和分页容纳计算。
- `progress.md`：追加本轮仪表盘最近归档面板布局记录。
- 回滚方式：还原本轮 `frontend/src/components/dashboard/DashboardArchive.vue` 的对应 hunk，并删除本段进度记录。

## 2026-06-24 - Task: 修复仪表盘任务流导入说明过早截断
### What was done
- 移除任务流导入说明 chip 的固定 220px 宽度限制，改为占用当前行剩余可用宽度。
- 保留超长文本单行省略，避免极端长文件名挤压状态按钮和操作菜单。

### Testing
- `cd frontend && npm run build`：通过。Vite 仅输出既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。

### Notes
- `frontend/src/components/dashboard/DashboardActiveTasks.vue`：任务说明 chip 改为可伸展布局，解决概览页导入处理文本右侧留白仍截断的问题。
- `progress.md`：追加本轮仪表盘任务流布局修复记录。
- 回滚方式：还原本轮 `frontend/src/components/dashboard/DashboardActiveTasks.vue` 中 `dash-task-badge-chip` 和 chip class 的对应 hunk，并删除本段进度记录。

## 2026-06-24 - Task: 修复概览右侧最近归档任务执行中抖动
### What was done
- 右侧最近归档只保留终态任务快照，不再把处理中任务混进归档列表。
- 静默刷新归档数据时不再点亮加载态，减少任务执行期间卡片反复闪烁和上下跳动。

### Testing
- `cd frontend && npm run build`：通过。仅保留既有 VueUse pure 注释、lottie-web eval 和 chunk 体积 warning。

### Notes
- `frontend/src/views/Dashboard.vue`：收紧最近归档的数据来源，并把静默刷新与可见 loading 分离，避免任务执行过程中的列表抖动。
- `progress.md`：追加本轮概览最近归档抖动修复记录。
- 回滚方式：还原本轮 `frontend/src/views/Dashboard.vue` 的对应 hunk，并删除本段进度记录。

## 2026-06-24 - Task: 修复服务器视频预览被 gzip 干扰
### What was done
- 让库存媒体预览在视频、音频、图片和 `206 Range` 响应上跳过 gzip，避免浏览器已经缓存到播放点后仍然卡顿。
- 追加了回归测试，确认视频 Range 响应保留 `206`、`Content-Range` 和 `Accept-Ranges`，且不再带 `Content-Encoding: gzip`。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile app\api\routes.py tests\test_library_browser_api.py`：通过。
- 独立 `TestClient(app)` 脚本：`/openapi.json` 仍返回 `content-encoding: gzip`，`/api/library/browser/preview` 的视频 Range 响应返回 `206`、`Content-Range: bytes 0-99/...`、`Content-Length: 100`，且无 `content-encoding`。
- `backend\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q -k video_preview_keeps_range_response_uncompressed`：因测试库 `kikoerumanager_test` 无法连接而失败，属于环境问题，不是本次代码路径失败。

### Notes
- `backend/app/api/routes.py`：新增媒体感知 gzip 响应器，让视频、音频、图片和 Range 响应跳过压缩。
- `backend/tests/test_library_browser_api.py`：新增视频预览 Range 回归测试。
- `docs/TESTING.md`：补充媒体预览不进 gzip 的行为说明。
- `progress.md`：追加本轮服务器视频预览 gzip 修复记录。
- 回滚方式：还原本轮 `backend/app/api/routes.py`、`backend/tests/test_library_browser_api.py` 和 `docs/TESTING.md` 的对应 hunk，并删除本段进度记录。

## 2026-06-26 - Task: 修复 DLsite 代理连接池临时卡死后需要重启下载
### What was done
- DLsite HTTP 请求遇到超时、网络错误或协议错误后，会主动丢弃共享 `httpx` 客户端连接池，再按原有退避逻辑重试。
- 保留原有短熔断、一次性客户端兜底和代理配置逻辑，避免代理隧道临时坏状态一直留到进程重启才恢复。

### Testing
- `.venv\Scripts\python.exe -c "import py_compile, tempfile, pathlib; out = pathlib.Path(tempfile.gettempdir()) / 'kikoerumanager_dlsite_service_check.pyc'; py_compile.compile('backend/app/core/dlsite_service.py', cfile=str(out), doraise=True); print('py_compile ok')"`：通过。
- `.venv\Scripts\python.exe -` 真实调用 `get_dlsite_service().get_product_info("RJ01609989")`：通过，返回 `product True`、`requested RJ01609989`；仅输出既有 brotli/brotlicffi 缺失降级 warning，不影响取数。
- `git diff --check -- backend/app/core/dlsite_service.py`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `backend/app/core/dlsite_service.py`：新增 DLsite 传输错误后的 HTTP 客户端连接池重建，避免代理/连接池临时坏状态持续影响后续请求。
- `progress.md`：追加本轮 DLsite 代理连接池恢复修复记录。
- 回滚方式：还原本轮 `backend/app/core/dlsite_service.py` 中 `_reset_client_after_transport_error` 及调用点的对应 hunk，并删除本段进度记录。

## 2026-06-26 - Task: 设置页新增 DLsite 连接测试
### What was done
- 设置页“外部服务 / ASMR 同步下载”的元数据代理旁新增“测试 DL 连接”按钮，可直接测试当前输入框里的 DLsite 代理，不需要先保存配置。
- 后端新增 DLsite 连通性测试接口，使用一次性 HTTP 客户端请求 DLsite product API，返回代理状态、HTTP 状态、耗时、测试 RJ 和标题，并对代理地址做脱敏。
- 连通性测试兼容 DLsite product API 的 list 返回结构，并补充代理连接失败、超时、网络异常的可读错误文案。

### Testing
- `.venv\Scripts\python.exe -m py_compile backend/app/core/dlsite_service.py backend/app/api/routes.py`：通过。
- `.venv\Scripts\python.exe -` 真实调用 `get_dlsite_service().test_connectivity(...)`：通过；当前配置代理 `http://127.0.0.1:7890` 与直连两组都返回 `success=true`、`HTTP 200`、`title_present=true`，测试 RJ 为 `RJ01609989`。
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告。
- `git diff --check -- backend/app/core/dlsite_service.py backend/app/api/routes.py frontend/src/api/index.js frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `backend/app/core/dlsite_service.py`：新增 DLsite 连通性测试、临时代理覆盖、代理脱敏、product API list 解析和测试错误文案。
- `backend/app/api/routes.py`：新增 `/api/dlsite/connectivity-test` POST 接口，接收当前设置页输入的 `http_proxy`。
- `frontend/src/api/index.js`：新增 `configApi.testDlsiteConnection()` 调用后端测试接口。
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：在元数据代理配置旁新增测试按钮和结果卡片。
- `progress.md`：追加本轮设置页 DLsite 连接测试记录。
- 回滚方式：还原本轮上述 4 个代码文件中 DLsite 连接测试相关 hunk，并删除本段进度记录；上一段 DLsite 连接池重建属于独立修复，按上一段回滚说明单独处理。

## 2026-06-27 - Task: 收紧设置页 DLsite 测试按钮布局
### What was done
- 将“测试 DL 连接”固定在元数据代理输入框右侧，避免按钮被挤到下一行形成突兀的大按钮。
- 单独压缩该按钮高度、字号、内边距和内容间距，不影响其他设置页按钮。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：为元数据代理行新增不换行布局类，并缩小 DLsite 测试按钮。
- `progress.md`：追加本轮 DLsite 测试按钮布局调整记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `metadata-proxy-row` 和 `.dlsite-test-btn` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 继续缩小设置页 DLsite 测试按钮文字
### What was done
- 进一步压缩“测试 DL 连接”内联按钮的高度、内边距、字号、文字间距和图标尺寸。
- 覆盖 StatefulButton 内层 label 的字号，避免按钮外层字号被组件内部结构抵消。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：将 DLsite 测试按钮收紧为更小的内联胶囊样式，并单独缩小按钮内图标与 label。
- `progress.md`：追加本轮 DLsite 测试按钮字体缩小记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `.dlsite-test-btn` 内层字号、间距、图标尺寸相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 设置页查重结果增加 DLsite 主图预览
### What was done
- Kikoeru 查重测试结果卡增加右侧 DLsite 主图预览，让命中结果和作品本体更容易对应。
- 复用项目已有 DLsite 封面目录规则按 RJ 拼接主图 URL，并在图片加载失败时尝试缩略图后隐藏坏图。
- 查重结果卡改为左右布局，窄屏自动收成单列，避免挤压文字内容。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：为 Kikoeru 查重测试结果增加 DLsite 主图、封面 URL 拼接、图片失败降级和响应式布局。
- `progress.md`：追加本轮查重主图预览记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeru-result-layout`、`buildDlsiteCoverUrl`、`handleKikoeruCoverError` 和查重结果卡图片相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 修正设置页查重主图比例
### What was done
- 将 Kikoeru 查重结果右侧 DLsite 主图从竖向裁切改为 4:3 横向预览。
- 图片渲染从 `cover` 改为 `contain`，完整保留 DLsite 主图比例，不再裁掉标题和人物边缘。
- 放大右侧图片位并保留窄屏自适应，确保图片仍固定在结果卡右侧展示。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：调整 Kikoeru 查重主图容器宽度、比例和 `object-fit`，让主图按原比例完整显示在右侧。
- `progress.md`：追加本轮查重主图比例修正记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `.kikoeru-result-layout` 和 `.kikoeru-result-cover` 尺寸 / 比例 / `object-fit` 相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 调整设置页查重主图到左侧并利用下方空间
### What was done
- 将 Kikoeru 查重结果里的 DLsite 主图从右侧移动到左侧，右侧保留状态、本次检查和标题等长文本。
- 把请求 RJ、命中结果、服务器已有和检查范围移动到主图下方，以两列信息块填充原本空白区域。
- 保留 4:3 原比例主图和移动端单列自适应布局。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：重排 Kikoeru 查重结果卡，把主图和关键摘要放到左列，长文本放到右列。
- `progress.md`：追加本轮查重主图布局调整记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeru-result-visual`、`kikoeru-result-meta` 和查重结果卡模板重排相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 优化设置页查重结果卡空间与边线
### What was done
- 将 Kikoeru 查重结果卡调整为上方主内容区和下方整宽摘要区，避免左右列高度差导致大片空白。
- 主内容区保留左侧 DLsite 主图、右侧长文本；请求 RJ、命中结果、服务器已有和检查范围改为底部四列摘要。
- 移除结果卡顶部 inset 高光线条，让卡片边缘更干净。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：重排 Kikoeru 查重结果卡结构，底部铺满摘要信息，并去除结果卡顶部白色高光。
- `progress.md`：追加本轮查重结果卡视觉优化记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeru-result-main`、`kikoeru-result-meta`、`.service-result-card` 阴影和结果卡模板相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 强化设置页查重结果可读性
### What was done
- 将 Kikoeru 查重结果里的本次检查 RJ 串改为独立 chip，避免一长串文本难读。
- 给“服务器已有”状态和底部服务器已有值增加 badge 样式，提升命中信息辨识度。
- 调整底部摘要区列宽，让“检查范围”获得更宽空间；中窄屏下检查范围独占整行，避免文字被挤出或异常换行。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：为查重 RJ 列表、服务器已有命中状态和检查范围摘要增加专用布局与视觉样式。
- `progress.md`：追加本轮查重结果可读性优化记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeru-rj-chip`、`kikoeru-owned-*`、`kikoeru-result-meta-wide` 相关 hunk，并删除本段进度记录。
## 2026-06-27 - Task: 优化查重结果标签与底部摘要布局
### What was done
- 将 Kikoeru 查重结果中的圆角胶囊改为更克制的小矩形标签，降低过度圆角带来的突兀感。
- 本次检查 RJ 标签按原作、简中、繁中、英文附加不同颜色，方便快速区分关联语言版本。
- 底部摘要改为带背景的信息块，并重新分配列宽；服务器已有和检查范围不再被窄列强行拆得很乱。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：为查重 RJ 标签增加语言 class、调整标签圆角与颜色，并重排底部摘要信息块。
- `progress.md`：追加本轮查重标签和底部摘要布局优化记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeruLinkedLabelClass`、`kikoeru-rj-chip.*`、`kikoeru-owned-*` 和 `kikoeru-result-meta` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 移除查重结果命中提示竖线和原作内框
### What was done
- 移除 Kikoeru 查重结果顶部“服务器已有”提示左侧的绿色竖线。
- 去掉底部“服务器已有”值内部的标签框，让 `RJ...(原作)` 回到普通摘要文本显示。
- 删除不再使用的 `kikoeru-owned-badge` 样式，避免残留无用规则。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/ServicesSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/ServicesSettingsPanel.vue`：去掉顶部命中提示左侧强调线，并移除底部服务器已有值的内层 badge 样式。
- `progress.md`：追加本轮命中提示竖线和原作内框移除记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/ServicesSettingsPanel.vue` 中 `kikoeru-owned-line`、`kikoeru-owned-badge` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 修正 AI 字幕模型配置布局
### What was done
- 将 AI 字幕连接配置里的模型选择框从叠层改为图标、输入、下拉按钮三列布局，避免图标和文字错位。
- 移除模型平台图标的白色底框；暗色模式下仅对 OpenAI 黑色 SVG 做反白显示。
- 缩小 API Key 输入框字号和高度，让它与同组设置项更一致。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：重排模型组合输入框、去除平台图标底色，并压小 API Key 输入字号。
- `progress.md`：追加本轮 AI 字幕设置布局修正记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `model-combo`、`model-platform-*` 和 `ai-api-key-input` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 细化 AI 字幕模型图标前缀样式
### What was done
- 将模型输入框前面的平台图标从独立大色块改为更小的内联前缀。
- 移除模型输入框内部对通用 `field-input` 样式的依赖，由组合控件统一绘制背景，避免图标区和文本区出现色块断层。
- 收紧下拉按钮宽度和圆角，让模型选择框整体更像一个完整输入控件。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：缩小模型平台图标前缀，移除内部 `field-input` 类，并改为组合控件统一背景。
- `progress.md`：追加本轮模型图标前缀样式优化记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中模型输入 class、`model-combo`、`model-platform-*` 和 `model-combo-input` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 优化 AI 字幕模型调用和连接测试
### What was done
- 将 AI 字幕正式模型调用改为优先流式请求，并补充请求开始、流式首包、完成和 JSON 解析日志；流式不支持时只在明确识别到不支持流式的错误后退回非流式。
- 将设置页“测试连接”从完整字幕配对调用改为轻量 JSON 探测，限制为短超时、低 token、无重试，避免测试按钮触发长时间真实配对请求。
- 缩短模型列表刷新链路的后端 HTTP 超时和前端等待上限，并在前端测试结果里展示探测方式、流式状态和耗时。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\ai_subtitle_match_service.py backend\app\api\routes.py`：通过。
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- backend/app/core/ai_subtitle_match_service.py backend/app/api/routes.py frontend/src/api/index.js frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `backend/app/core/ai_subtitle_match_service.py`：新增 LiteLLM 流式优先调用、轻量连接探测、模型列表短超时和阶段日志。
- `frontend/src/api/index.js`：将 AI 字幕模型列表和测试连接接口的前端等待上限降为 35 秒。
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：展示模型列表耗时、测试探测方式和流式状态，并补齐失败兜底结果字段。
- `progress.md`：追加本轮 AI 字幕模型调用和连接测试优化记录。
- 回滚方式：还原本轮 `backend/app/core/ai_subtitle_match_service.py` 中 `_extract_litellm_stream_delta`、`_complete_*`、`_probe_model_connection`、`list_models` 和 `test_connection` 相关 hunk；还原 `frontend/src/api/index.js` 的 AI 字幕接口 timeout hunk；还原 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中模型列表耗时、测试结果探测/流式展示和格式化函数相关 hunk；并删除本段进度记录。

## 2026-06-27 - Task: 移除 AI 字幕模型图标黑块感
### What was done
- 将 AI 字幕模型框前面的平台图标移出输入框深色背景，让图标直接显示在透明区域上。
- 将模型输入框从图标列、输入列、下拉列的分段控件改为“外侧图标 + 普通输入框”结构。
- 去掉模型下拉按钮左侧分隔线，避免右侧也形成一块独立深色区域。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：重排模型输入组合样式，平台图标不再落在输入框深色背景内，并移除下拉按钮分段线。
- `progress.md`：追加本轮 AI 字幕模型图标黑块感修正记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `model-combo`、`model-platform-badge`、`model-combo-input`、`model-combo-dd` 和 `model-combo-trigger` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 重新整合 AI 字幕模型图标到输入框
### What was done
- 将 AI 字幕模型平台图标重新放回模型输入框内部，不再作为外侧独立元素显示。
- 模型输入框改为单一完整控件，由外层统一绘制背景、边框和聚焦态；内部输入框透明无边框。
- 保留下拉按钮在右侧内部对齐，并继续去掉左侧分隔线，避免回到三段式深色块布局。

### Testing
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。另一个重复并发构建进程因同时清理 `dist/assets` 报 `EPERM`，不是本轮代码错误。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：将模型图标从外置布局改回输入框内部绝对定位，并让输入框与下拉按钮共用同一控件背景。
- `progress.md`：追加本轮模型图标重新整合记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `model-combo`、`model-platform-badge`、`model-combo-input`、`model-combo-dd` 和 `model-combo-trigger` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 实测修正 AI 字幕模型输入框暗色断层
### What was done
- 在 `http://localhost:5556/settings` 的 AI 配对页实际检查模型输入组合控件，确认黑块感不是平台图标背景，而是内部输入框被全局暗色输入框样式覆盖成另一块深灰。
- 将模型输入框内部 input 固定为透明、无边框、无阴影，并补高优先级暗色选择器，避免再被全局暗色规则染色。
- 保持外层组合控件统一绘制背景、边框和聚焦态，图标和下拉按钮继续在同一个控件内对齐。

### Testing
- `http://localhost:5556/settings` AI 配对页浏览器实测：修复前 `.model-combo-input` computed `backgroundColor` 为 `rgb(43, 44, 48)`；修复后为 `rgba(0, 0, 0, 0)`，`boxShadow` 为 `none`，字号为 `13px`。
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：让模型输入框内层 input 透明化，并增加暗色模式高优先级兜底样式，消除深色断层。
- `progress.md`：追加本轮 5556 实测调试后的修复记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `model-combo-input` 背景透明、暗色高优先级选择器相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: AI 字幕连接测试改为 hi 探测
### What was done
- 将设置页 AI 配对“测试连接”从字幕 JSON 能力探测收窄为发送 `hi` 的基础模型回应测试。
- 后端连接测试改为非流式、无 `response_format`、`max_tokens=16`、不重试和短硬超时，避免模型服务慢响应拖到前端超时。
- 前端测试结果改为展示回应状态、探测方式和回复预览，并明确提示该测试不验证字幕 JSON 输出。
- 在测试文档补充 AI 连接测试语义和验证命令，避免后续把它误当完整字幕配对验证。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\ai_subtitle_match_service.py`：通过。
- `cd frontend && npm run build`：通过；仅输出既有 VueUse / lottie / chunk size 构建警告，并完成资源预压缩。
- `git diff --check -- backend/app/core/ai_subtitle_match_service.py frontend/src/api/index.js frontend/src/components/settings/AISubtitleSettingsPanel.vue docs/TESTING.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `backend/app/core/ai_subtitle_match_service.py`：将设置页连接测试改为 `hi` 基础探测，并返回回复预览、探测超时和 token 用量。
- `frontend/src/api/index.js`：调整 AI 字幕测试接口的前端等待上限，配合后端短硬超时避免继续显示前端超时。
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：更新连接测试说明和结果展示，从 JSON 能力改为模型回应、探测方式和回复预览。
- `docs/TESTING.md`：增加 AI 字幕设置连接测试的验证语义和命令。
- `progress.md`：追加本轮 AI 连接测试改为 hi 探测记录。
- 回滚方式：还原本轮 `backend/app/core/ai_subtitle_match_service.py` 中 `_probe_model_connection` 和 `test_connection` 的 hi 探测相关 hunk；还原 `frontend/src/api/index.js` 的 AI 测试接口 timeout hunk；还原 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中连接测试说明、结果字段和探测格式化相关 hunk；删除 `docs/TESTING.md` 的 AI 字幕设置连接测试小节，并删除本段进度记录。

## 2026-06-27 - Task: 修正 AI 模型列表切换中转串缓存
### What was done
- 将 AI 字幕模型列表缓存签名绑定到 Base URL、API 版本、组织、代理和 API Key 指纹，避免不同中转或密钥共用旧模型缓存。
- 切换 AI 连接配置时递增模型列表请求序号，并在响应返回后校验发起时签名，废弃旧中转的迟到响应。
- 模型列表获取失败时不再沿用上一轮模型，只保留当前连接真实获取或缓存命中的模型列表。

### Testing
- `cd frontend && npm run build`：通过；两个已启动构建进程均完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：为模型列表缓存和异步刷新增加连接签名隔离，切换中转后不会显示上一中转模型。
- `progress.md`：追加本轮 AI 模型列表缓存隔离记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `aiSubtitleModelsRequestId`、`hashCachePart`、`buildAISubtitleModelsCacheSignature`、`saveAISubtitleModelsCache` 和 `fetchAISubtitleModels` 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 清理 AI 模型切换后的旧模型值
### What was done
- 将 AI 字幕模型列表本地缓存版本升到 v2，旧版已经串过的浏览器缓存不再参与当前下拉。
- 有当前中转模型列表时，不再把“当前填写的模型”强行塞回下拉选项。
- 切换 Base URL、API Key、代理、API Version 或 Organization 后自动清空旧模型字段；成功加载当前中转模型列表时，如果旧模型不在当前列表里也会清空。

### Testing
- `cd frontend && npm run build`：通过；两个最终构建进程均完成资源预压缩。
- `git diff --check -- frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：升级模型列表缓存版本，并在连接作用域变化、模型列表刷新和缓存加载时清理不属于当前中转的旧模型值。
- `progress.md`：追加本轮旧模型值清理记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `AI_SUBTITLE_MODELS_CACHE_VERSION`、`aiSubtitleModelOptions` 的手填模型插入条件、`clearAISubtitleModelIfMissingFromRows` 和连接作用域清空模型相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 补齐 AI 模型下拉智谱官方图标
### What was done
- 从智谱 BigModel 官方站点下载本地图标资源，作为 GLM / 智谱 AI 模型的下拉图标。
- 将智谱模型平台元数据接入本地图标，`glm-*` 模型不再显示空图标。
- 没有保留非官方文字占位图标，图标来源记录到 AI 平台图标说明里。

### Testing
- `frontend/src/assets/ai-platforms/zhipu.png`：已确认来源为 `https://bigmodel.cn/img/icons/apple-touch-icon-152x152.png`，文件头为 PNG，并完成视觉检查。
- `cd frontend && npm run build`：通过；构建产物包含 `dist/assets/zhipu-CWmkm5qz.png`，并完成资源预压缩。
- `git diff --check -- frontend/src/components/common/aiModelPlatformMeta.js frontend/src/assets/ai-platforms/README.md frontend/src/assets/ai-platforms/zhipu.png progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/assets/ai-platforms/zhipu.png`：新增智谱 BigModel 官方图标资源。
- `frontend/src/components/common/aiModelPlatformMeta.js`：将智谱平台 `iconSrc` 指向本地图标，供 GLM 模型下拉项渲染。
- `frontend/src/assets/ai-platforms/README.md`：记录智谱图标来源。
- `progress.md`：追加本轮官方图标补齐记录。
- 回滚方式：删除 `frontend/src/assets/ai-platforms/zhipu.png`，还原 `frontend/src/components/common/aiModelPlatformMeta.js` 中 `zhipuIconUrl` 导入、`AI_PLATFORM_ICON_URLS.zhipu` 和智谱 `iconSrc` hunk，删除 `frontend/src/assets/ai-platforms/README.md` 的 zhipu 来源行，并删除本段进度记录。

## 2026-06-27 - Task: 补齐 AI 模型下拉主流厂商图标和识别
### What was done
- AI 模型下拉补齐国内主流厂商识别和本地官方图标：通义千问、百度千帆、腾讯混元、MiniMax、零一万物、阶跃星辰、讯飞星火、商汤日日新、书生浦语、OpenBMB，以及前一轮已下载的 MiMo、智谱、Moonshot、百川、火山、SiliconFlow、Groq、Cohere。
- 将 `gemini` 映射到 Google 官方 Gemini 图标，将 `claude` 映射到 Anthropic 官方 favicon；`grok / x-ai / x_ai` 补齐到 xAI 映射，不再出现空图标。
- 前端下拉和后端 favicon 缓存使用一致的厂商别名 / host 识别，覆盖 `qwen3-*`、`ernie-*`、`hunyuan-*`、`abab*`、`step-*`、`spark-*`、`internlm-*`、`minicpm-*` 等常见模型 ID。
- 本机对 xAI / Grok 官方 favicon 源 `x.ai`、`grok.com`、`x.com`、`abs.twimg.com` 拉取失败，未新增非官方 Grok 图标文件；当前 Grok 继续使用项目已有 xAI/X 本地图标。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend/app/core/ai_provider_icon_service.py`：通过。
- `git diff --check -- backend/app/core/ai_provider_icon_service.py frontend/src/components/common/aiModelPlatformMeta.js frontend/src/assets/ai-platforms/README.md progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。
- `Get-ChildItem -File frontend/src/assets/ai-platforms ...`：确认新增官方图标文件存在，包括 `anthropic-official.ico`、`gemini.svg`、`deepseek.ico`、`qwen.ico`、`baidu.ico`、`hunyuan.ico`、`minimax.ico`、`yi.ico`、`stepfun-ai.ico`、`iflytek.ico`、`sensenova.ico`、`internlm.ico`、`openbmb.ico`。
- `cd frontend && npm run build`：通过；构建产物包含新增厂商图标资源，并完成资源预压缩。

### Notes
- `backend/app/core/ai_provider_icon_service.py`：补齐国内主流模型厂商和 Gemini / Claude / Grok 的后端厂商识别、官方 favicon 候选源和别名匹配。
- `frontend/src/components/common/aiModelPlatformMeta.js`：补齐模型下拉使用的本地官方图标、厂商元数据、host 识别和别名匹配。
- `frontend/src/assets/ai-platforms/README.md`：记录新增官方图标来源。
- `frontend/src/assets/ai-platforms/anthropic-official.ico`、`gemini.svg`、`deepseek.ico`、`qwen.ico`、`baidu.ico`、`hunyuan.ico`、`minimax.ico`、`yi.ico`、`stepfun-ai.ico`、`iflytek.ico`、`sensenova.ico`、`internlm.ico`、`openbmb.ico`：新增模型厂商本地图标资源。
- `progress.md`：追加本轮主流模型厂商图标和识别补齐记录。
- 回滚方式：还原本轮 `backend/app/core/ai_provider_icon_service.py`、`frontend/src/components/common/aiModelPlatformMeta.js` 和 `frontend/src/assets/ai-platforms/README.md` 的对应 hunk，删除上述新增图标文件，并删除本段进度记录。

## 2026-06-27 - Task: 修正 AI 模型下拉图标比例和白底
### What was done
- 移除 AI 模型下拉图标统一强加的白色背景、内边距和阴影，避免官方图标被套白壳、比例被压小。
- 将下拉图标改为无 padding 的固定 18px 容器，用 `object-fit: contain` 保持官方图标原始比例。
- 给模型图标组件补厂商 key class，只在暗色模式下对 OpenAI、xAI、OpenRouter 这类黑色单色图标做反白处理。

### Testing
- `cd frontend && npm run build`：通过；构建完成并完成资源预压缩。早先并发构建出现过 `EPERM` 清理冲突，原因是多个 Vite 同时清空同一个 `dist/assets`，后续构建均已通过。
- `git diff --check -- frontend/src/components/common/aiModelPlatformMeta.js frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：去掉 AI 模型菜单图标的白底、padding、阴影，并按厂商精准处理暗色单色图标。
- `frontend/src/components/common/aiModelPlatformMeta.js`：为模型图标组件增加厂商 key class，供样式层识别具体厂商。
- `progress.md`：追加本轮 AI 模型下拉图标比例和白底修正记录。
- 回滚方式：还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `.ai-model-option-icon`、暗色图标 filter 和当前模型图标 class 相关 hunk；还原 `frontend/src/components/common/aiModelPlatformMeta.js` 中 `createAIPlatformIconComponent` 的 key class hunk，并删除本段进度记录。

## 2026-06-27 - Task: 放大 AI 模型下拉内部图标
### What was done
- 将 AI 模型下拉图标从图片直接参与布局改为固定图标槽包裹内部图片，避免被通用下拉的 14px 图标尺寸压缩。
- 下拉菜单图标槽放大到 34px，内部图片默认 30px，MiMo 这类官方方形字标使用 34px 完整显示。
- 暗色模式的 OpenAI、xAI、OpenRouter 单色图标反白改为作用到内部图片，不影响图标槽和其它彩色厂商图标。

### Testing
- `cd frontend && npm run build`：通过；两条误并发启动的构建均完成资源预压缩。
- `git diff --check -- frontend/src/components/common/aiModelPlatformMeta.js frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/common/aiModelPlatformMeta.js`：模型图标组件改为 `span` 图标槽包裹 `img`，保留厂商 key class。
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：放大 AI 模型菜单内部图标尺寸，并为 MiMo 官方字标做更大显示尺寸。
- `progress.md`：追加本轮下拉内部图标比例修正记录。
- 回滚方式：还原本轮 `frontend/src/components/common/aiModelPlatformMeta.js` 中 `createAIPlatformIconComponent` 的 wrapper hunk；还原本轮 `frontend/src/components/settings/AISubtitleSettingsPanel.vue` 中 `.ai-model-option-icon`、`.ai-model-option-icon-img` 和暗色 filter 相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 回退 AI 模型下拉图标放大方案
### What was done
- 撤销 AI 模型下拉内部图标 34px 放大方案，避免模型列表左侧图标过大、视觉压迫。
- 将模型图标组件恢复为直接渲染 `img`，保留厂商 key class，继续支持按厂商处理暗色单色图标。
- 下拉菜单图标恢复到 18px，仍保留透明背景、无 padding、无阴影，不回到白色外框状态。

### Testing
- `cd frontend && npm run build`：通过；两条误并发启动的构建均完成资源预压缩。
- `git diff --check -- frontend/src/components/common/aiModelPlatformMeta.js frontend/src/components/settings/AISubtitleSettingsPanel.vue progress.md`：通过，仅提示工作区 LF/CRLF 转换 warning。

### Notes
- `frontend/src/components/common/aiModelPlatformMeta.js`：撤回图标 wrapper，恢复直接 `img` 渲染。
- `frontend/src/components/settings/AISubtitleSettingsPanel.vue`：撤回 34px 图标槽和内部图片样式，恢复 18px 菜单图标。
- `progress.md`：追加本轮图标放大方案回退记录。
- 回滚方式：如需回到大图标方案，可恢复上一段记录中的 wrapper、`.ai-model-option-icon-img`、34px 图标槽和内部图片 filter 相关 hunk；如需彻底回到更早白底样式，则还原前一轮白底修复 hunk。

## 2026-06-27 - Task: 修复系统通知跳转落点
### What was done
- 修正任务中心生成的通知落点：HTTP 外链下载进入 ASMR 同步的 HTTP tab，百度上传回库存页，社团补全通知携带社团和 RJ 定位参数。
- 系统铃铛点击时增加旧通知兜底解析，避免历史通知里的错误 `/conflicts`、错误百度 tab 或缺 tab 路径继续乱跳。
- 社团补全页面支持从 URL query 定位到指定社团或 RJ，点击通知后会切换到对应社团并尽量定位作品。
- 保留真正的问题作品 / 等待人工处理通知跳转到问题作品，只把成功态导入 / 解压完成通知纠正回库存或对应工作台。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\task_center_service.py app\core\task_notification_service.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_task_center_service.py tests\test_task_notification_service.py -q -k "route_hint or route_hints or conflict_retry or baidu_netdisk_upload"`：通过，`4 passed, 13 deselected`；仅有既有 deprecation warning 和 pytest cache warning。
- `cd frontend; npm run build`：通过；仅有既有 VueUse PURE 注释、lottie eval 和 chunk size warning。

### Notes
- `backend/app/core/task_center_service.py`：修正通知 route hint，社团补全补 query 参数，冲突重试成功态不再强制覆盖到问题作品。
- `backend/app/core/task_notification_service.py`：排除百度上传被误识别成下载部分成功通知。
- `frontend/src/components/system/NotificationPanel.vue`：点击铃铛通知时统一解析并修正历史错误落点。
- `frontend/src/views/CircleCompletion.vue`：支持 `circle_id`、`circle_name`、`rjcode` query 定位社团和作品。
- `progress.md`：追加本轮通知跳转修复记录。
- 回滚方式：还原上述四个代码文件中本轮通知跳转相关 hunk，并删除本段进度记录。

## 2026-06-27 - Task: 修正库存页删除刷新与移动弹窗索引浏览
### What was done
- 修正库存删除后的刷新一致性：删除成功后立即清本地浏览缓存，并同步通知库存索引删除，避免前端乐观删除后又被旧索引或目录 TTL 缓存刷回来。
- 本地索引读取时增加磁盘存在性校验，过滤已不存在或类型已变化的索引条目，并按过滤结果修正分页 total。
- “移动到...”弹窗的本地目录浏览改为优先读取库存索引；索引未就绪或库内无快照条目时回退到本地单层目录浏览，避免空索引吞掉真实文件。
- 文件夹内容索引读取增加本地目标目录校验和 stale 汇总回退，避免已删除目录或旧目录统计继续污染弹窗结果。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\library_manager.py`：通过。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py::test_local_inventory_reads_prefer_usable_index_snapshot tests\test_library_browser_api.py::test_list_files_coalesces_identical_inflight_requests -q`：通过，`2 passed`。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py::test_library_browser_endpoints_support_multi_library -q`：通过，`1 passed`。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py -q`：单进程输出通过，`25 passed`。验证过程中曾误并发启动重复 pytest，重复进程出现 PostgreSQL schema 初始化冲突和临时目录竞争，不属于本轮代码失败。

### Notes
- `backend/app/core/library_manager.py`：清理本地目录浏览缓存、删除时同步追赶索引、索引读路径过滤本地 stale 条目，并让移动弹窗优先走库存索引。
- `backend/tests/test_library_browser_api.py`：补充本地库存索引 fake 的同步删除行为，覆盖删除后移动弹窗不再显示已删文件。
- `progress.md`：追加本轮库存删除刷新和移动弹窗索引浏览修复记录。
- 回滚方式：还原本轮 `backend/app/core/library_manager.py` 和 `backend/tests/test_library_browser_api.py` 的对应 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 修正概览页任务卡进度说明布局
### What was done
- 将概览页任务卡的当前步骤说明从任务标签同一行移出，改为独立左对齐行，避免长进度文本被挤到状态按钮旁边。
- 为步骤说明补充最大宽度和任意位置换行，长文件名或进度文案不会横向撑破任务卡。

### Testing
- `cd frontend; npm run build`：通过；仅有既有 VueUse PURE 注释、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/dashboard/DashboardActiveTasks.vue`：调整任务卡 chip 与当前步骤说明的布局，并新增 `.dash-task-step-line` 宽度约束。
- `progress.md`：追加本轮概览任务卡布局修复记录。
- 回滚方式：还原本轮 `frontend/src/components/dashboard/DashboardActiveTasks.vue` 中 current_step 独立行和 `.dash-task-step-line` 的 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 去除概览页社团补全重复社团名
### What was done
- 修正概览页任务卡副标题显示规则：当副标题与标题完全相同，就不再渲染副标题。
- 社团补全任务仍保留标题里的社团名和“社团补全”业务标签，只去掉标题下方重复的一行社团名。

### Testing
- `cd frontend; npm run build`：通过；两条误并发启动的构建均完成资源预压缩，仅有既有 VueUse PURE 注释、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/dashboard/DashboardActiveTasks.vue`：为 `displaySubtitle()` 增加标题 / 副标题去重判断。
- `progress.md`：追加本轮社团补全重复社团名修复记录。
- 回滚方式：还原本轮 `frontend/src/components/dashboard/DashboardActiveTasks.vue` 中 `displaySubtitle()` 和 `normalizeComparableText()` 的对应 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 修复解压任务日志进度展示
### What was done
- 修正系统日志里的解压任务进度标题：优先显示具体压缩包文件名，不再只显示泛化的“解压任务”。
- 后端任务进度日志增加压缩包来源标签，并兼容 Windows / Linux 路径分隔符，避免 Windows 路径下源文件名解析失败。
- 前端系统日志同时兼容新旧进度日志格式，活动中的合成进度行会按秒刷新持续时间；百分比继续跟随最新流式日志更新。

### Testing
- `cd backend; ..\.venv\Scripts\python.exe -m py_compile app/core/task_engine.py`：通过。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_task_engine.py::TestTaskEngine::test_task_update_progress -q`：通过。
- 后端一次性断言验证：解压进度日志包含 `【RJ12345678.7z】`，且不再显示 `手动导入` 作为压缩包名，通过。
- `cd frontend; npm run build`：通过；仅有既有 Rollup / lottie / chunk size warning。

### Notes
- `backend/app/core/task_engine.py`：进度日志携带压缩包名，提交日志解析源文件名时兼容 Windows 路径。
- `frontend/src/views/Logs.vue`：解析新旧任务进度格式，合成解压进度行显示具体压缩包，并让活动持续时间动态刷新。
- `progress.md`：追加本轮解压任务日志进度展示修复记录。
- 回滚方式：执行 `git restore -- backend/app/core/task_engine.py frontend/src/views/Logs.vue`，并手动删除本段 `progress.md` 记录。

## 2026-06-28 - Task: 修正字幕补配预检解包失败阻断导入
### What was done
- 修正字幕补配预检状态机：来源压缩包在预检阶段因密码、嵌套包或临时解包失败未拿到字幕时，不再把自动入库任务直接判定为致命失败。
- 对仍存在的来源压缩包保留待处理单，并允许用户在字幕补配页点击“导入并加入工作台”后再走完整解压链路扫描字幕，复用解压配置与嵌套压缩包处理。
- 保留真实“已解开但没有字幕”的拦截语义，避免空字幕包被误放入工作台。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\linked_subtitle_import_service.py backend\tests\test_linked_subtitle_import_service.py`：通过。
- 使用项目 `.venv` 直接调用 `LinkedSubtitleImportService._refresh_preview_execution_state()` 验证 `missing_password` 预检状态：返回 `can_stage_pending=True`、`can_execute=True`。
- `pytest backend/tests/test_linked_subtitle_import_service.py ...` 多次卡在测试环境初始化阶段未输出结果，已停止残留 pytest 进程，未拿到完整 pytest 结果。

### Notes
- `backend/app/core/linked_subtitle_import_service.py`：新增执行时可重新解包的预检状态判断，并避免 pending 创建后立即二次 staging 远程大包。
- `backend/tests/test_linked_subtitle_import_service.py`：补充预检解包失败仍保留待处理单、且不立即重新解包的覆盖用例。
- `progress.md`：追加本轮字幕补配预检修复记录。
- 回滚方式：还原本轮 `backend/app/core/linked_subtitle_import_service.py` 和 `backend/tests/test_linked_subtitle_import_service.py` 的对应 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 修复 DLsite 关联链退化导致翻译作误按新作入库
### What was done
- 修正 DLsite 页面元数据 fallback 的翻译信息语义：页面标题、封面等元数据只能证明页面可读，不能证明该 RJ 是日语原作。
- 字幕补配预检新增“不确定 DLsite 关联链”状态：当关联链只剩自身、target 为空，但页面标题或来源文本带中文 / 翻译信号时，不再降级为“非翻译新作”。
- 任务引擎在该状态下把任务转入 `waiting_retry`，等待后续重新跑预检；这属于 DLsite 临时不完整，不进入 `LINKED_WORK` 问题作品。
- 任务中心为普通导入的 `waiting_retry` 任务开放手动重试动作，避免只能等定时调度。
- 补充回归覆盖，锁住页面 fallback 不可信、preview 不再 `treat_as_new_work`、任务引擎会拦截并进入等待重试三个关键边界。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_service.py backend\app\core\linked_subtitle_import_service.py backend\app\core\task_engine.py backend\tests\test_linked_subtitle_import_service.py backend\tests\test_circle_completion_bonus_detection.py`：通过。
- 使用项目 venv 直接断言验证：DLsite 页面 fallback 的 `translation_info.is_original=False` 且 `source=page_metadata_unverified`；`RJ01621937` 半残关联链 preview 返回 `dlsite_linkage_uncertain=True`、`treat_as_new_work=False`；任务引擎 `_should_block_uncertain_dlsite_linkage()` 会拦截不可执行 preview，并通过 `set_waiting_retry()` 进入 `waiting_retry`，结果 `direct waiting-retry verification passed`。
- `.\venv\Scripts\python.exe -m pytest ...`：未拿到结果；`python -m pytest --version` 在当前环境也会启动后无输出卡住，已停止残留 pytest 进程。`import pytest` 可正常返回版本 `7.4.3`，卡点在 pytest 命令启动层，不是本轮业务断言失败。
- 复核服务器日志 `\\Elena\docker\prekikoeru\data\app.log`：`1231ddb2-dd25-48cf-80ea-d5009fe58ee2` 首次任务确实跑了预检，`RJ01621937` 页面元数据标题含 `【繁体中文版】... [みんなで翻訳]`，但旧逻辑仍写 `target_rj=`、`is_translation_work=False`、`按新作直接解压入库`；`f8ff954c-6d56-40c4-9df6-e269e82561b4` 是问题作品重试并带 `skip_retry_precheck=True`。

### Notes
- `backend/app/core/dlsite_service.py`：页面元数据解析出的 `translation_info` 改为未验证状态，不再默认原作。
- `backend/app/core/linked_subtitle_import_service.py`：新增翻译文本信号与不确定关联链识别，阻止半残 DLsite 结果进入新作入库分支。
- `backend/app/core/task_engine.py`：新增不确定 DLsite 关联链的任务拦截，并转入等待重试。
- `backend/app/core/task_center_service.py`：为普通导入 / system 域的 `waiting_retry` engine task 暴露手动重试动作。
- `backend/tests/test_circle_completion_bonus_detection.py`：覆盖页面元数据 fallback 不再标记为原作。
- `backend/tests/test_linked_subtitle_import_service.py`：覆盖 preview 与任务引擎拦截逻辑。
- `progress.md`：追加本轮 DLsite 关联链退化修复记录。
- 回滚方式：还原上述六个代码 / 测试文件中本轮 DLsite linkage uncertain / waiting_retry 相关 hunk，并删除本段进度记录；若只回滚拦截行为，至少要同步还原 `linked_subtitle_import_service.py` 和 `task_engine.py`，避免 preview 字段残留但任务不处理。

## 2026-06-28 - Task: 修正大包 unknown 探测密码优先级
### What was done
- 修正解压密码候选排序：文件名 / RJ 绑定密码仍优先，通用密码库密码延后到 RJ±1 之后，避免大包 unknown 探测次数上限被通用密码耗尽。
- 预读取压缩包清单和正式解压路径共用同一排序规则，保留指定密码重试只用指定密码的语义。
- 补充回归用例，锁住“只有 RJ-1 正确时，三个通用密码不能挤掉 RJ±1 尝试机会”的边界。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\extract_service.py tests\test_extract_service.py`：通过。
- 使用项目 venv 直接调用 `ExtractService._try_extract()` 验证大包 unknown 场景：实际完整解压尝试顺序为 `RJ01649862`、`RJ01649863`、`RJ01649861`，最终使用 `RJ01649861` 成功，通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_extract_service.py::TestExtractService::test_try_extract_large_unknown_tries_rj_before_generic_passwords tests\test_extract_service.py::TestExtractService::test_try_extract_large_archive_tries_sniffed_password_before_rj_guess tests\test_extract_service.py::TestExtractService::test_try_extract_uses_rj_password_before_empty_for_encrypted_archive -q --basetemp .pytest-codex-extract-password-order`：未进入用例，`tests/conftest.py` 初始化 PostgreSQL 测试库时失败；同配置直接连接 `postgres`、`template1`、`kikoerumanager_test` 均被 127.0.0.1:5432 服务端断开，`sslmode=disable` 也失败。

### Notes
- `backend/app/core/extract_service.py`：新增密码库候选拆分逻辑，并调整清单预读 / 正式解压的密码顺序。
- `backend/tests/test_extract_service.py`：新增大包 unknown 探测下 RJ±1 不被通用密码挤掉的回归测试。
- `progress.md`：追加本轮大包密码优先级修复记录。
- 回滚方式：还原本轮 `backend/app/core/extract_service.py` 和 `backend/tests/test_extract_service.py` 的对应 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 修正大包密码探测上限误判无正确密码
### What was done
- 修正大包 unknown 探测上限语义：RJ 号、RJ±1、文件名嗅探、指定密码等高可信候选不受通用密码兜底次数限制。
- 通用 / 默认这类低可信候选仍保留完整解压兜底上限，避免 4GB 级压缩包被几十个通用密码反复全量解压。
- 达到上限后只跳过本轮未验证候选，不再把未真正解压验证过的密码写入负缓存，也不再把整轮结果包装成“无正确密码”。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\extract_service.py tests\test_extract_service.py`：通过。
- 直接调用 `ExtractService._try_extract()` 验证：RJ / RJ±1 全部完整尝试，通用密码只尝试到上限；被上限跳过的通用密码未进入负缓存，最终返回 `light_probe_unknown`，通过。
- 直接调用 `ExtractService._try_extract()` 验证 `RJ01649862.rar` 场景：通用密码不会抢在 RJ±1 前面，`RJ01649861` 可在第三次完整解压机会成功，通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_extract_service.py::TestExtractService::test_try_extract_large_archive_caps_unknown_probe_full_extracts tests\test_extract_service.py::TestExtractService::test_try_extract_large_unknown_tries_rj_before_generic_passwords -q --basetemp .pytest-codex-extract-password-limit`：通过，`2 passed`；仅有既有 deprecation warning 和 pytest cache warning。

### Notes
- `backend/app/core/extract_service.py`：调整大包 unknown 探测上限，只限制低可信候选；未验证候选不写负缓存，最终返回 `light_probe_unknown`。
- `backend/tests/test_extract_service.py`：更新大包 unknown 上限回归测试，覆盖高可信候选不受限、低可信候选受限且未验证不缓存。
- `progress.md`：追加本轮大包密码探测上限误判修复记录。
- 回滚方式：还原本轮 `backend/app/core/extract_service.py` 和 `backend/tests/test_extract_service.py` 的对应 hunk，并删除本段进度记录。

## 2026-06-28 - Task: 修复 AI 字幕配对按钮暗色态误显灰色
### What was done
- 确认服务器运行配置中 `ai_subtitle_matching.enabled: true`，问题不是 AI 字幕配对未启用。
- 修正字幕筛选与配对工作台暗色样式：AI 配对按钮不再被普通按钮兜底规则覆盖成灰色，保留明确的青色可操作态。
- 同步处理库存字幕工作台和字幕导入工作台两处共享按钮，避免同一组件在不同入口继续误显不可用。

### Testing
- `cd frontend; npm run build`：通过。构建仅输出既有 Rollup pure annotation、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/library/SubtitleInspectorWorkbench.vue`：给 AI 配对按钮增加专用 class，并补暗色态 / hover 颜色。
- `frontend/src/App.vue`：将 AI 配对按钮排除出库存字幕工作台普通按钮暗色兜底。
- `frontend/src/dark-mode.css`：将 AI 配对按钮排除出字幕导入工作台普通按钮与彩色背景暗色兜底。
- `progress.md`：追加本轮 AI 字幕配对按钮暗色态修复记录。
- 回滚方式：还原上述三个前端文件中 `subtitle-ai-pair-button` 相关 hunk，并删除本段进度记录。

## 2026-06-29 - Task: 修正大包密码库候选被探测上限跳过
### What was done
- 移除大包 unknown 探测里把 `密码库-通用` 视为低可信并按 3 次完整解压上限跳过的逻辑。
- 保留效率优化边界：空密码在存在密码候选时仍只做轻量探测并跳过完整解压，文件名 / RJ 绑定和 RJ±1 仍排在通用密码库前面，负缓存仍只记录实际完整验证失败的密码。
- 更新回归测试，锁住“大包轻量探测无法定性时，密码库候选必须全部进入完整解压验证，轮完后才返回密码错误”的业务前提。
- 更新产品介绍中密码工作台语义，明确密码库候选会作为兜底完整轮查。
### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\extract_service.py tests\test_extract_service.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_extract_service.py::TestExtractService::test_try_extract_large_archive_tries_all_vault_passwords_when_probe_unknown tests\test_extract_service.py::TestExtractService::test_try_extract_large_unknown_tries_rj_before_generic_passwords tests\test_extract_service.py::TestExtractService::test_try_extract_large_archive_tries_sniffed_password_before_rj_guess -q --basetemp .pytest-codex-extract-password-vault`：未进入用例，`tests/conftest.py` 初始化 PostgreSQL 测试库 `kikoerumanager_test` 超时，pytest 进程已精确结束。
- 使用项目 venv 直接调用 `ExtractService._try_extract()` 验证大包 unknown 场景：完整解压顺序为 `RJ01623101`、`RJ01623102`、`RJ01623100`、`vault-a`、`vault-b`、`vault-c`，密码库候选全部验证后返回 `wrong_password`，通过。
- 使用项目 venv 直接调用 `ExtractService._try_extract()` 验证后置密码库命中场景：`vault-c` 作为第三个通用密码库候选能在前序候选失败后成功命中；成功后记录密码使用时因本机 PostgreSQL 超时打出日志，但不影响解压结果。
- `git diff --check -- backend\app\core\extract_service.py backend\tests\test_extract_service.py docs\INTRODUCTION.md`：无空白错误；仅提示工作区 CRLF/LF 换行风格。
### Notes
- `backend/app/core/extract_service.py`：删除 `UNKNOWN_PROBE_FULL_EXTRACT_LIMIT` 和低可信候选跳过分支，探测 unknown 的非空密码候选继续进入完整解压。
- `backend/tests/test_extract_service.py`：把旧的“候选被上限截断”测试改为“密码库候选必须全部验证”的回归测试，并移除旧上限 monkeypatch。
- `docs/INTRODUCTION.md`：补充密码库候选作为兜底完整轮查的业务说明。
- `progress.md`：追加本轮大包密码库候选轮查修复记录。
- 回滚方式：还原上述三个代码 / 文档文件中本轮关于 `UNKNOWN_PROBE_FULL_EXTRACT_LIMIT`、unknown 探测跳过分支、测试期望和密码库语义说明的 hunk，并删除本段进度记录。

## 2026-07-02 - Task: 修复字幕补配预检超时后临时解包继续后台运行
### What was done
- 为字幕补配压缩包预检增加同路径 in-flight 去重，同一个 `archive_path` 同一时间只启动一次真实 archive preview / 临时解包。
- 改造预检超时处理：超时时显式 cancel 内部 preview task，并把临时解包用的 probe task 标记为取消，确保 7zz / unar 路径能进入终止流程。
- 修正非 7z 子进程取消路径：`unar` 等 `_run_subprocess_command()` 在协程取消时先 terminate，必要时 kill，不再只等待 `communicate()` 自然返回。
- 补充回归测试覆盖 in-flight 去重、超时取消 probe task、非 7z 子进程取消终止。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\linked_subtitle_import_service.py backend\app\core\extract_service.py backend\tests\test_linked_subtitle_import_service.py backend\tests\test_extract_service.py`：通过。
- 使用项目 venv 直接运行异步回归脚本验证：同一路径并发 preview 只执行一次；预检 timeout 会取消内部 task；临时解包 cancel 会标记 probe task；`_run_subprocess_command()` cancel 会 terminate 子进程，全部通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest ...`：当前 pytest 主入口在本机 venv 中卡住，`pytest --version` / `pytest.main(['--version'])` 也会挂起；已清理本轮启动的残留 pytest 进程，未把 pytest 结果当作通过。

### Notes
- `backend/app/core/linked_subtitle_import_service.py`：新增压缩包预检 in-flight 管理，并在 timeout / coroutine cancel 时显式取消内部 preview 与 probe task。
- `backend/app/core/extract_service.py`：补齐非 7z 子进程的取消终止逻辑，避免 unar 后台继续跑。
- `backend/tests/test_linked_subtitle_import_service.py`：新增字幕补配预检去重和取消回归测试。
- `backend/tests/test_extract_service.py`：新增非 7z 子进程 cancel 后 terminate 的回归测试。
- `progress.md`：追加本轮字幕补配预检超时取消修复记录。
- 回滚方式：还原上述四个代码 / 测试文件中本轮 in-flight、cancel、terminate 相关 hunk，并删除本段进度记录。

## 2026-07-02 - Task: 优化大 ZIP 中文密码兼容解压速度
### What was done
- 调整 ZIP 中文密码兼容后端顺序：大 ZIP 优先走 native `unar`，避免 Python `zipfile` 慢速全量解密 / 解压。
- 保留小 ZIP 的 Python `zipfile` 优先路径，避免小文件为启动外部进程付出额外成本。
- 新增 `KIKOERUMANAGER_ZIP_COMPAT_UNAR_FIRST_MIN_BYTES` 阈值，默认 64MB；大于等于该大小且存在 `unar` 时优先使用 `unar`。
- 更新兼容后端进度文案，区分 `Python ZIP 中文密码兼容解压` 与 `unar ZIP 中文密码兼容解压`。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\extract_service.py backend\tests\test_extract_service.py backend\app\core\linked_subtitle_import_service.py backend\tests\test_linked_subtitle_import_service.py`：通过。
- `git diff --check -- backend\app\core\extract_service.py backend\tests\test_extract_service.py backend\app\core\linked_subtitle_import_service.py backend\tests\test_linked_subtitle_import_service.py progress.md`：无空白错误，仅有既有 CRLF/LF 提示。
- 使用项目 venv 直接运行回归脚本验证：大 ZIP 优先 `unar` 且不先跑 Python `zipfile`；小 ZIP 仍保留 Python 优先，全部通过。脚本末尾记录密码使用因本机 PostgreSQL 连接超时报日志，不影响解压路径判断。

### Notes
- `backend/app/core/extract_service.py`：新增大 ZIP 兼容解压优先 `unar` 的阈值与调度逻辑。
- `backend/tests/test_extract_service.py`：新增大 ZIP 中文密码优先 `unar` 的回归测试，并固定小 ZIP Python 优先行为。
- `progress.md`：追加本轮大 ZIP 中文密码兼容解压速度优化记录。
- 回滚方式：还原本轮 `ZIP_COMPAT_UNAR_FIRST_MIN_BYTES`、`try_unar_zip_compat_backend` 调度顺序和对应测试 hunk，并删除本段进度记录。

## 2026-07-02 - Task: 修复 ZIP 中文密码兼容误判错密码为可用
### What was done
- 修正 ZIP 密码字节探测：只用真正加密的 ZIP 条目验证密码，不再让未加密说明文件 / 小文件把任意密码误判为可用。
- 限制密码字节探测读取量，最多读取 `ZIP_PASSWORD_BYTE_PROBE_BYTES`，避免探测阶段对大条目做长时间读取。
- 大 ZIP 在 `unar` 中文密码兼容失败后不再回退到 Python `zipfile` 全量解压，错误通用中文密码会快速失败并继续轮询后续候选。
- 补充“未加密小文件 + 加密 GBK 条目”的混合 ZIP 回归，锁住错密码不能通过探测的行为。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\extract_service.py backend\tests\test_extract_service.py backend\app\core\linked_subtitle_import_service.py backend\tests\test_linked_subtitle_import_service.py`：通过。
- `git diff --check -- backend\app\core\extract_service.py backend\tests\test_extract_service.py backend\app\core\linked_subtitle_import_service.py backend\tests\test_linked_subtitle_import_service.py progress.md`：无空白错误，仅有既有 CRLF/LF 提示。
- 使用项目 venv 直接运行回归脚本验证：混合 ZIP 中错误密码 `諷詠` 不再通过探测，正确密码可识别为 `gbk/cp936`；大 ZIP `unar` 失败后不会调用 Python `zipfile` 全量解压，通过。
- 精准 pytest 用例未作为通过依据：本机 PostgreSQL 测试库 `kikoerumanager_test` 连接超时，pytest 在 `tests/conftest.py` 初始化阶段失败。

### Notes
- `backend/app/core/extract_service.py`：收紧 ZIP 密码字节探测条件，限制探测读取量，并阻止大 ZIP 在 `unar` 失败后进入 Python 全量兼容解压。
- `backend/tests/test_extract_service.py`：新增混合 ZIP 错密码误判回归测试和大 ZIP 跳过 Python 兼容后端验证。
- `progress.md`：追加本轮 ZIP 中文密码兼容误判错密码修复记录。
- 回滚方式：还原本轮 `_probe_zip_password_bytes`、大 ZIP `unar` 失败后跳过 Python 后端的对应 hunk，并删除本段进度记录。

## 2026-07-02 - Task: 修复任务中心详情文件树重复渲染
### What was done
- 统一任务中心详情文件树的路径规范化，合并 `\` / `/`、`./`、带根目录和不带根目录的同一文件写法。
- 修正绝对路径混入文件树时的展示 key：当路径里已经包含任务根目录时，先裁掉根目录之前的本机路径前缀，再参与合并，避免渲染成“根目录 / D: / ... / 根目录 / 文件”的重复树。
- 保留普通相对路径层级，不对 `foo/downloads/bar` 这类合法相对目录做中间截断。

### Testing
- 使用本地 Node 片段验证：`track01.flac`、`[RJ12345678] Work/track01.flac`、`D:/Downloads/[RJ12345678] Work/track01.flac` 会合并为单条 `[RJ12345678] Work/track01.flac`，且普通相对路径 `foo/downloads/bar.mp3` 不被误截断。
- `cd frontend; npm run build`：通过。
- `git diff --check -- frontend/src/views/Tasks.vue`：通过，仅提示工作区换行风格。

### Notes
- `frontend/src/views/Tasks.vue`：新增任务详情文件树路径规范化与绝对路径前缀裁剪，并让上传 / 下载 / 快照 / 过滤项映射、目录 key 和树构建共用同一套路径 key。
- `progress.md`：追加本轮任务中心文件树重复渲染修复记录。
- 回滚方式：还原 `frontend/src/views/Tasks.vue` 中本轮 `normalizeTaskFileTreePath`、`stripTaskFileTreePathBeforeRoot`、文件树映射和目录 key 相关 hunk，并删除本段进度记录。

## 2026-07-03 - Task: 修复 Google Drive 大文件病毒扫描警告页下载
### What was done
- 在 Google Drive 真实下载阶段增加 warning HTML 自愈：遇到病毒扫描警告页时解析 `download-form` 隐藏参数，拼出带 `confirm` / `uuid` 的确认下载 URL，并立即重试文件流下载。
- 保留配额超限、权限不足等 HTML 错误页的失败判定，不把错误页保存成压缩包。
- 补充回归测试覆盖先返回病毒扫描警告页、再跳转确认 URL 下载真实文件流的场景。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\http_download_service.py backend\tests\test_http_download_service.py`：通过。
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_http_download_service.py -k "google_drive_confirm_url_from_warning_html or download_google_drive_item_skips_virus_warning_html or download_google_drive_item_reports_quota_html"`：未进入用例执行，当前工作区已有 `backend/app/models/database.py` 变更导致 `dlsite_bonus_probe_cache` 表重复定义，pytest 在 conftest 导入阶段失败。

### Notes
- `backend/app/core/http_download_service.py`：下载阶段遇到 Google Drive warning HTML 时解析确认 URL 并重试。
- `backend/tests/test_http_download_service.py`：新增 Google Drive 病毒扫描警告页跳过回归测试。
- `progress.md`：追加本轮 Google Drive 大文件 warning 页下载修复记录。
- 回滚方式：还原上述两个代码 / 测试文件中本轮 `tried_warning_confirm_urls`、HTML warning 确认 URL 重试逻辑和新增测试 hunk，并删除本段进度记录。

## 2026-07-03 - Task: 修复问题中心合并工作台暗色样式
### What was done
- 为问题中心目录差异工作台补齐暗色主题覆盖，统一弹窗外壳、头部、工具栏、筛选、统计、左右文件行和底部操作区的暗色背景、边框与文字层级。
- 修正合并列表在暗色模式下浅灰泛白的问题，并保留新增、删除、变更、选中等差异状态的可读语义色。
- 同步覆盖当前保留的旧表格回退样式，避免非主路径状态下出现浅色表格闪白。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`：新增目录差异工作台暗色主题覆盖样式。
- `progress.md`：追加本轮问题中心合并工作台暗色样式修复记录。
- 回滚方式：还原 `frontend/src/components/conflicts/ConflictMergeWorkbench.vue` 中本轮“暗色态：目录差异工作台”样式块，并删除本段进度记录。

## 2026-07-03 - Task: 优化批量删除字幕文件后的库存索引同步
### What was done
- 优化 `delete_subtrees()` 的批量删除路径：先精确识别待删根路径类型，文件路径走精确删除和聚合祖先目录 delta，不再进入目录子树递归统计。
- 目录路径和索引未命中路径保留原有递归删除兜底，避免 stale index 下目录根缺失但子项残留时删不干净。
- 将库存索引子树匹配从 `LIKE path/%` 统一改为 btree 范围条件，覆盖删除统计、子树查询、批量子目录 / 文件汇总、同库 / 跨库移动改写等路径。
- 新增批量删除 35 个字幕文件路径的回归测试，断言文件批删不触发 `jsonb_to_recordset + LEFT JOIN library_index_entries` 的递归统计 SQL，且父目录 size / file_count 与索引状态 delta 正确归零。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\library_index\snapshot_store.py backend\tests\test_library_index_self_mutation.py`：通过。
- `rg -n "LIKE|\.like\(|_subtree_like_pattern|_escape_like_literal" backend/app/core/library_index/snapshot_store.py`：子树匹配相关 `LIKE` 已清除，仅剩搜索用 `ILIKE` 和 RJ 前缀 `rjcode.like()`。
- `cd backend; venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py -q`：未进入用例执行；当前工作区已有 `backend/app/models/database.py` 变更在 `DLsiteBonusProbeCache` 上重复定义 `dlsite_bonus_probe_cache` 表，pytest 在 `tests/conftest.py` 导入阶段失败。

### Notes
- `backend/app/core/library_index/snapshot_store.py`：新增文件批删快路径，保留目录 / 未命中路径递归兜底，并统一子树范围匹配。
- `backend/tests/test_library_index_self_mutation.py`：新增 35 个字幕文件批删回归测试和 SQL 捕获断言。
- `progress.md`：追加本轮库存索引批量删除性能优化记录。
- 回滚方式：还原上述两个代码 / 测试文件中本轮 `delete_subtrees()`、子树范围匹配和新增测试 hunk，并删除本段进度记录。

## 2026-07-03 - Task: 引入 PostgreSQL 慢 SQL 与搜索索引治理
### What was done
- 将操作历史搜索收敛到 `activity_logs.searchable_text`，写入时同步投影 summary、路径、RJ、task、batch、session，并提供启动兼容迁移和 Alembic 迁移回填。
- 将任务中心搜索收敛到 `task_center_items.searchable_text`，移除 title / business_key / engine_task_id 多列 OR 查询路径，并把旧单列 trigram 索引列入清理。
- 为密码库、安全网关、社团补全补齐表达式 / 字段 trigram 索引，相关搜索统一转义 `%/_/!`，避免裸 contains / LIKE 全表扫。
- 扩展数据库维护性能快照，返回搜索域索引状态、缺失 / 旧索引提示和慢 SQL 建议，并新增 `/api/database/maintenance/search-status`。
- 设置页 PostgreSQL 维护卡片展示搜索索引状态和诊断建议；新增慢 SQL 搜索治理文档。
- 清理当前工作区已有的重复 `DLsiteBonusProbeCache` / `DLsiteBonusProbeDate` 模型定义，保留与 20260702 Alembic 迁移一致的一组，解除后端导入阻断。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile app/config/settings.py app/models/database.py app/core/activity_log_service.py app/core/task_center_materialization_service.py app/core/database_maintenance_service.py app/core/circle_completion_service.py app/core/security_gate_service.py app/api/routes.py tests/test_activity_log_service.py tests/test_routes_maintenance_config.py tests/test_task_center_service.py tests/test_database_observability.py tests/test_library_index_fts.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。
- `rg -n "TaskCenterItem\.(title|business_key|engine_task_id)\.ilike|PasswordEntry\..*contains|ProcessedArchive\..*contains|SecurityGateAuthLog\.ip_address\.contains|idx_activity_logs_(summary|source_path|rjcode|task_id|batch_id)_trgm ON|idx_task_center_(title|business_key|engine_task_id)_trgm ON" backend/app backend/alembic frontend/src`：无匹配。
- `cd backend; venv\Scripts\python.exe -m pytest tests/test_activity_log_service.py tests/test_routes_maintenance_config.py tests/test_task_center_service.py tests/test_database_observability.py tests/test_library_index_fts.py -q`：未完成；重复 DLsite 模型定义修复后，当前环境 `kikoerumanager_test` PostgreSQL 测试库连接超时，pytest 在 `tests/conftest.py` 初始化阶段失败。

### Notes
- `backend/app/models/database.py`：新增 `activity_logs.searchable_text`、搜索索引规格、兼容迁移回填和旧索引清理；同时移除重复 DLsite 探测模型定义。
- `backend/app/core/activity_log_service.py`：操作历史写入时生成 `searchable_text`。
- `backend/app/api/routes.py`：操作历史 / 密码库 / 已处理归档搜索改为索引友好 SQL，并新增数据库维护搜索状态接口。
- `backend/app/core/task_center_materialization_service.py`：任务中心物化列表搜索只走 `searchable_text`。
- `backend/app/core/circle_completion_service.py`、`backend/app/core/security_gate_service.py`：社团补全和门禁日志搜索改为转义后的 trigram 友好查询。
- `backend/app/core/database_maintenance_service.py`：新增搜索索引域诊断、性能建议和维护快照扩展。
- `backend/app/config/settings.py`、`backend/config/config.yaml`：新增慢 SQL 监控和搜索后端配置默认值。
- `backend/alembic/versions/20260612_0001_postgresql_baseline.py`、`backend/alembic/versions/20260703_0001_slow_sql_search_governance.py`：同步 baseline 与新增迁移。
- `frontend/src/api/index.js`、`frontend/src/components/settings/DatabaseShrinkCard.vue`：接入搜索索引状态和性能建议展示。
- `backend/tests/test_activity_log_service.py`、`backend/tests/test_routes_maintenance_config.py`、`backend/tests/test_task_center_service.py`、`backend/tests/test_database_observability.py`：补充搜索治理相关回归。
- `docs/slow-sql-search-governance.md`：新增慢 SQL 与搜索索引治理说明。
- `progress.md`：追加本轮慢 SQL / 搜索治理记录。
- 回滚方式：还原上述文件中本轮 `searchable_text`、trigram 搜索索引、维护诊断、前端展示和测试文档相关 hunk；若只回滚本轮搜索治理，不要恢复已删除的重复 DLsite 模型定义，除非同时修正其重复表名问题。

## 2026-07-03 - Task: 补跑慢 SQL 治理后端回归
### What was done
- 在 PostgreSQL 测试库恢复后补跑慢 SQL / 搜索治理相关后端回归，并修正测试工具让测试 schema 初始化也执行兼容迁移。
- 对齐现有配置与任务中心异步缓存测试：resource budget 断言补 `library_index_write`，默认空数据库密码保持空字符串，任务中心 cached helper mock 改为 async。
- 确认新增 activity search trigram 索引在测试 schema 中创建成功。

### Testing
- `cd backend; venv\Scripts\python.exe -m pytest tests/test_activity_log_service.py tests/test_routes_maintenance_config.py tests/test_task_center_service.py tests/test_database_observability.py tests/test_library_index_fts.py -q`：通过，`64 passed`。
- `git diff --check -- backend/alembic/versions/20260612_0001_postgresql_baseline.py backend/alembic/versions/20260703_0001_slow_sql_search_governance.py backend/app/api/routes.py backend/app/config/settings.py backend/app/core/activity_log_service.py backend/app/core/circle_completion_service.py backend/app/core/database_maintenance_service.py backend/app/core/security_gate_service.py backend/app/core/task_center_materialization_service.py backend/app/models/database.py backend/config/config.yaml backend/tests/postgres_test_utils.py backend/tests/test_activity_log_service.py backend/tests/test_routes_maintenance_config.py backend/tests/test_task_center_service.py backend/tests/test_database_observability.py frontend/src/api/index.js frontend/src/components/settings/DatabaseShrinkCard.vue docs/slow-sql-search-governance.md progress.md`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `backend/tests/postgres_test_utils.py`：测试 schema 初始化和 truncate 前置准备改为同时执行 `_migrate_compat_schema()`。
- `backend/tests/test_routes_maintenance_config.py`：配置断言对齐当前默认 resource budget 和空密码返回语义。
- `backend/tests/test_task_center_service.py`：任务中心缓存测试的异步 helper mock 改为 `AsyncMock`。
- `progress.md`：追加本轮补跑回归记录。
- 回滚方式：还原上述测试 / 测试工具 hunk，并删除本段进度记录。

## 2026-07-03 - Task: 调整概览任务标签单行展示
### What was done
- 将概览页任务流卡片从左侧独立大图标布局调整为内容区内联图标布局，任务图标现在显示在任务标签行最前面。
- 将任务类型、作品 / 归档标签和当前阶段标签合并到同一条不换行的 meta 行，长文本改为截断省略，避免阶段标签掉到下一行。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/dashboard/DashboardActiveTasks.vue`：调整概览任务流卡片结构和标签行 CSS 约束。
- `progress.md`：追加本轮概览任务标签单行展示记录。
- 回滚方式：还原 `frontend/src/components/dashboard/DashboardActiveTasks.vue` 中本轮 grid 列、`dash-task-meta-row`、内联图标和阶段标签相关 hunk，并删除本段进度记录。

## 2026-07-03 - Task: 保持通知面板打开时侧栏展开
### What was done
- 通知面板打开期间，左侧栏复用原有 hover / pinned 展开态，不再因为鼠标离开铃铛区域自动收起。
- 保留原通知铃铛位置、通知面板结构、透明遮罩和原侧栏动画，不移动入口、不改通知组件内部行为。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/App.vue`：读取通知中心 `panelOpen` 状态，并把原侧栏展开选择器同步覆盖到 `is-notification-panel-open`。
- `progress.md`：追加本轮通知面板打开时侧栏保持展开记录。
- 回滚方式：还原 `frontend/src/App.vue` 中本轮 `useNotifications`、`notificationPanelOpen` 和 `is-notification-panel-open` 选择器相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 排查服务器日志慢接口并补状态轮询本地缓存
### What was done
- 聚合 `\\Elena\docker\prekikoeru\data\app.log` 中 118785 行日志，确认慢 SQL 证据不明显，主要卡顿集中在请求内同步重活、远程 / 文件 I/O 和高频状态轮询排队。
- 为任务中心 overview 增加 1 秒微缓存，避免导入 / 下载任务进度高频跳动时 dashboard 每次都重建 summary 聚合。
- 为 HTTP 下载和百度网盘状态接口增加 1 秒微缓存，避免轮询时重复清洗大体积 `download_files` metadata。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\task_center_service.py backend\app\api\routes.py`：通过。
- `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_task_center_service.py backend\tests\test_routes_maintenance_config.py -q`：通过，`44 passed`。

### Notes
- `backend/app/core/task_center_service.py`：新增 overview 级短缓存，降低 `/api/task-center/overview` 高频轮询重建成本。
- `backend/app/api/routes.py`：新增下载状态短缓存，并接入 `/api/http-download/status`、`/api/baidu-netdisk/status`。
- `progress.md`：追加本轮服务器日志慢接口排查和状态轮询优化记录。
- 回滚方式：还原上述两个后端文件中本轮 `OVERVIEW_CACHE_TTL_SECONDS`、`_overview_cache`、`_DOWNLOAD_STATUS_CACHE` 和状态接口缓存相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 修复社团补全特典探测 0 命中
### What was done
- 修复 DLsite 隐藏特典候选生成：当同发售日只有一个公开 RJ，或公开 RJ 相邻没有数字缺口时，改为围绕公开 RJ 生成受限前后窗口候选，避免探测数量直接为 0。
- 修复隐藏特典命中条件：日期只用于圈定探测批次，不再要求隐藏特典自身的 product/info 发售日等于当前批次日期，避免同社团真实特典被误杀。
- 补充回归测试覆盖单公开 RJ 生成窗口候选、相邻公开 RJ 保留边缘候选、大缺口不全量扩散，以及跨日期隐藏特典仍可命中。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py -q`：通过，`4 passed`。
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。
- 使用本地社团 `RG62878` / リリムワークス现有 10 个发售日现场复算：候选数从 0 变为 640；复用探测缓存后命中 `RJ01569983`，标题为“【期間限定4大特典】幼妻ロリ/オホ♡プリンセス...【兎月りりむ。からのプレゼント】”。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增公开 RJ 边缘窗口候选，并放宽隐藏特典日期硬过滤。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 DLsite 特典探测候选与命中条件回归测试。
- `progress.md`：追加本轮社团补全特典修复记录。
- 回滚方式：还原上述后端服务和测试文件中本轮 `DEFAULT_EDGE_WINDOW`、`_build_gap_candidates`、`_hidden_bonus_matches` 相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 社团补全特典探测改用原作 RJ 全量日期
### What was done
- 将特典探测的公开端点和发售日来源改为只读取 `CircleWork.canonical_rjcode`，不再混入 `display_rjcode` / `linked_rjcodes` 的翻译版发售日。
- 社团补全页“特典补全”按钮改为 deep 模式，默认探测该社团所有已索引原作发售日，而不是只探最近 10 日。
- 任务去重 key 加入 `mode`，避免 deep 全量任务误复用旧 normal 范围任务。
- 补充回归测试覆盖 canonical 原作 RJ 选择，确认翻译版 display / linked RJ 不会进入特典探测端点。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py -q`：通过，`5 passed`。
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\app\api\routes.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。
- 使用本地社团 `RG62878` / リリムワークス复算：deep 发售日从混入翻译版的 84 日收敛为 42 个原作日期，已覆盖 `2025-05-03`、`2024-11-02`、`2025-08-30`、`2025-11-30`、`2026-01-01`、`2026-02-23` 等已知特典原作日期。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：特典探测公开 RJ 和日期枚举统一取 canonical 原作 RJ。
- `backend/app/api/routes.py`：特典补全任务 business key 加入 mode。
- `frontend/src/views/CircleCompletion.vue`：特典补全按钮启动 deep 全量模式。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 canonical-only 回归测试。
- `progress.md`：追加本轮原作 RJ 全量日期修复记录。
- 回滚方式：还原上述文件中本轮 `_public_original_worknos_from_rows`、`list_indexed_release_dates` / `_load_indexed_public_worknos` canonical-only、`business_key` mode 和前端 deep 参数相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 社团补全发售排序改用原作日期
### What was done
- 社团补全作品项新增 `original_release_date`，从 `CircleWork.canonical_rjcode` 对应的 `WorkMetadata.release_date` 读取原作日文版发售日。
- 发售时间升 / 降序排序改为优先使用 `original_release_date`，展示层仍保留当前首选版本的 `release_date`，避免简中 / 繁中 / 特典展示日期打乱原作时间线。
- 补充分页排序回归测试，覆盖“翻译版展示日期更晚，但原作日期更早”时仍按原作日期排序。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_circle_completion_paged_view.py -q`：通过，`7 passed`。
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\circle_completion_service.py backend\tests\test_circle_completion_paged_view.py`：通过。
- 使用本地社团 `RG62878` / リリムワークス实际拉取缺失作品第一页 `sort=release_desc`：`RJ01569979` 展示日期为 `2026-05-27`，但按原作日期 `2026-03-22` 排在 `RJ01578805(2026-05-04)` 后，符合原作时间线。

### Notes
- `backend/app/core/circle_completion_service.py`：作品项补 `original_release_date`，发售排序 timestamp 优先使用原作日期。
- `backend/tests/test_circle_completion_paged_view.py`：新增原作发售日期排序回归测试。
- `progress.md`：追加本轮社团补全发售排序修复记录。
- 回滚方式：还原上述两个代码 / 测试文件中本轮 `_completion_original_release_date`、`original_release_date`、`_completion_release_timestamp` 相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 修复社团补全全站日期页隐藏特典漏扫
### What was done
- 将 DLsite 特典探测恢复为“原作发售日当天公开 RJ 作为全站编号锚点”的策略：日期页所有公开 RJ 只用于生成受限小缺口候选，再用 product/info 的 maker_id 和隐藏特典条件做最终确认。
- 保留同社团公开原作 RJ 的边缘窗口候选，避免单公开 RJ 或相邻公开 RJ 现场仍然 0 候选。
- 为全站日期页候选单独设置 80 位小缺口上限，避免前端 deep 的 `gap_limit=500` 直接扩大到全站大缺口导致请求量爆炸。
- 任务结果汇总新增全站日期页公开锚点数和全站小缺口数，方便后续从日志判断候选来源。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py -q`：通过，`7 passed`。
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py`：通过。
- 使用真实 DLsite 日期页 `2025-06-28` 验证：当天公开锚点 253 个，小缺口候选 3573 个，候选集合已包含 `RJ01416572`。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：日期页抓取同时返回同社团公开 RJ 和全站公开 RJ；全站公开 RJ 只生成小缺口候选，不做边缘窗口扩散。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 `RJ01416572` 所在全站小缺口命中测试，以及大缺口跳过测试。
- `progress.md`：追加本轮全站日期页隐藏特典漏扫修复记录。
- 回滚方式：还原上述后端服务和测试文件中本轮 `DEFAULT_DATE_PAGE_GAP_LIMIT`、`include_edges`、`date_page_worknos`、`date_page_*` 结果字段相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 优化社团补全特典 product/info 批量探测
### What was done
- 将 DLsite `product/info/ajax` 隐藏特典探测从单 RJ 单 HTTP 改为批量 RJ 单 HTTP，请求使用逗号拼接的 `product_id`，批量失败时回退到原单条探测路径。
- 将特典补全默认 `batch_size` 从 200 提高到 500，并同步后端请求默认值和前端启动参数，减少大候选日期的 HTTP 批次数。
- 补充批量 product/info 单测，覆盖批量 URL 生成、特典字段归一，以及批量返回缺失 RJ 时写入 missing 特征。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_service_bulk_product_info.py backend\tests\test_dlsite_bonus_probe_service.py -q`：通过，`9 passed`。
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_service.py backend\app\core\dlsite_bonus_probe_service.py backend\app\api\routes.py backend\tests\test_dlsite_service_bulk_product_info.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。

### Notes
- `backend/app/core/dlsite_service.py`：新增批量 product/info URL 和 payload 拉取，`probe_product_info_features` 改为批量优先、失败回退单条。
- `backend/app/core/dlsite_bonus_probe_service.py`：特典探测默认批大小提高到 500。
- `backend/app/api/routes.py`：特典补全启动请求默认 batch_size 提高到 500。
- `frontend/src/views/CircleCompletion.vue`：特典补全启动参数同步 batch_size 500。
- `backend/tests/test_dlsite_service_bulk_product_info.py`：新增批量 product/info 探测回归测试。
- `progress.md`：追加本轮 product/info 批量探测优化记录。
- 回滚方式：还原上述文件中本轮 `_build_product_info_ajax_bulk_url`、`_fetch_product_info_ajax_payloads`、`probe_product_info_features` 批量逻辑和 batch_size 500 相关 hunk，删除新增测试文件，并删除本段进度记录。

## 2026-07-04 - Task: 优化社团补全特典断点复用
### What was done
- 为 DLsite 特典探测增加策略版本标识，完成记录写入 `deep:date-gap-v2`，避免旧策略记录被误当成新策略结果。
- 重复执行同一 maker / 发售日 / gap_limit 的特典探测时，若已有可复用 completed 记录，直接跳过该日期，不再重新抓日期页或批量请求 product/info。
- 兼容本轮策略版本前已经跑完的全站日期页记录：probe_count 明显超过边缘窗口的旧 deep 记录可复用；早期只扫 160 个边缘候选的记录不复用，避免漏扫。
- 任务汇总新增 `skipped_count`，用于观察重复执行时跳过了多少发售日。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_service_bulk_product_info.py backend\tests\test_dlsite_bonus_probe_service.py -q`：通过，`12 passed`。
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增策略版本、完成日期复用判断、cached completed 结果构造和汇总 skipped_count。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 completed 日期复用判断测试，覆盖当前策略、旧全站日期页记录和旧边缘-only 记录。
- `progress.md`：追加本轮断点复用优化记录。
- 回滚方式：还原上述服务和测试文件中本轮 `PROBE_STRATEGY_VERSION`、`_mode_key`、`_can_reuse_completed_date_row`、`_completed_date_row_result`、`skipped_count` 相关 hunk，并删除本段进度记录。

## 2026-07-04 - Task: 社团补全特典关联原作
### What was done
- 隐藏特典写入时查找同社团、同 maker、同原作发售日的非特典原作，并优先选择 RJ 编号距离最近的原作，避免同日多原作时错误挂链。
- 特典行保留独立作品记录，同时把 `linked_rjcodes` 写成原作 RJ + 特典 RJ，便于展示层识别其归属。
- 原作行追加特典 RJ 到 `linked_rjcodes`，同步标记 `has_bonus=True` 并补 `dlsite_bonus_probe` 来源标识。
- 同步写入 `WorkCanonicalLink(canonical=原作RJ, linked=特典RJ, link_type=bonus)`，让后续社团补全和关联链查询能直接识别特典已属于原作。

### Testing
- `$env:PYTHONPATH='backend'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_dlsite_service_bulk_product_info.py -q`：通过，`14 passed`。
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增特典原作选择、RJ 链合并、bonus canonical link upsert，并在特典写入时同步更新原作行。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增特典关联原作选择测试，覆盖同日同 maker 最近原作选择、不同 maker / 特典行不误挂。
- `progress.md`：追加本轮特典关联原作记录。
- 回滚方式：还原上述服务和测试文件中本轮 `WorkCanonicalLink` 导入、`_merge_rjcodes`、`_select_original_work_for_bonus`、`_upsert_bonus_canonical_link` 和 `_upsert_bonus_works` 关联写入相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 修复邮件新作特典探测覆盖早期原作日期
### What was done
- 邮件监听发现新作后，自动排队的 DLsite 隐藏特典探测改为同时扫描“邮件新作发售日”和“原作日本版发售日”，避免后发版 / 翻译版邮件只扫后发日期而漏掉早期特典。
- 邮件入口的特典探测任务参数对齐手动入口：`mode=new_release` 纳入 `business_key`，`batch_size` 提高到 500，避免旧去重键和较小批量拖慢或误复用任务。
- 修复邮件直入写 `WorkMetadata` 时把当前邮件 RJ 的发售日套到整条关联链的问题；现在当前 RJ 使用自身日期，canonical 原作优先读取自己的元数据日期。
- 返回给邮件新作分组的结果新增 `original_release_date`，让后续特典探测能直接拿原作日期作为扫描目标。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\email_watcher_service.py backend\app\core\dlsite_bonus_probe_service.py`：通过。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_dlsite_service_bulk_product_info.py -q`：通过，`14 passed`。

### Notes
- `backend/app/core/email_watcher_service.py`：邮件新作特典探测补原作日期集合、任务去重键和批量参数对齐新版策略，并修复关联链 metadata 日期污染。
- `progress.md`：追加本轮邮件新作特典探测修复记录。
- 回滚方式：还原 `backend/app/core/email_watcher_service.py` 中本轮 `_trigger_bonus_probe_for_new_releases`、`original_release_date`、`metadata_by_target`、`current_product_rjcodes` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 校正邮件新作特典探测日期语义
### What was done
- 按业务定义校正邮件入口：邮件检查到的新作发售日本身即视为本次特典探测的原作发售日。
- 回退多余的 canonical 原作日期追查、`original_release_date` 返回字段，以及按 canonical 额外扩展扫描日期的逻辑。
- 保留邮件新作自动排队特典探测、`mode=new_release` 去重键、`batch_size=500` 等必要修复。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\email_watcher_service.py backend\app\core\dlsite_bonus_probe_service.py`：通过。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_dlsite_service_bulk_product_info.py -q`：通过，`14 passed`。

### Notes
- `backend/app/core/email_watcher_service.py`：邮件特典探测仅使用邮件新作 `release_date` 作为扫描日期，保留新版任务参数与去重键。
- `progress.md`：追加本轮日期语义校正记录，覆盖上一条记录中“原作日期额外扩展”的错误表述。
- 回滚方式：还原 `backend/app/core/email_watcher_service.py` 中本轮 `_trigger_bonus_probe_for_new_releases` 日期集合相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 修复社团补全特典远距离编号漏扫
### What was done
- 定位 `RJ01314197` 查不到特典的根因：隐藏特典 `RJ01315736` 距离原作编号 `+1539`，旧算法的同社团原作边缘窗口只有 80，候选阶段直接漏掉。
- 新增同社团公开原作专用边缘窗口，至少扫描原作前后 2000 个 RJ；全站日期页小缺口仍保持 80，避免全站候选爆炸。
- 将特典探测策略版本提升到 `date-gap-v3`，旧 completed 记录不再复用，避免用户重新执行时直接跳过旧漏扫结果。
- 任务结果新增 `circle_edge_window`，后续从任务日志能看出当前同社团边缘扫描范围。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_dlsite_service_bulk_product_info.py -q`：通过，`15 passed`。
- 真实 DLsite 查询确认 `RJ01315736` 满足隐藏特典结构化条件：`maker_id=RG62878`、`release_date=2025-01-01`、`work_type=SOU`、`price=0`、`is_free=true`、`is_oly=true`、`wishlist_count=0`。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增 `DEFAULT_CIRCLE_EDGE_WINDOW`，同社团公开原作边缘候选改用宽窗口，策略版本升到 `date-gap-v3`。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 `RJ01314197 -> RJ01315736` 远距离特典候选回归测试，并更新旧完成记录复用测试。
- `progress.md`：追加本轮特典远距离编号漏扫修复记录。
- 回滚方式：还原上述服务和测试文件中本轮 `DEFAULT_CIRCLE_EDGE_WINDOW`、`edge_window_limit`、`date-gap-v3`、`circle_edge_window` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 校正社团补全特典候选为当天完整 RJ 范围
### What was done
- 按业务策略校正 DLsite 特典候选生成：全站日期页不再使用 `gap <= 80` 小缺口，而是取当天公开 RJ 的最小到最大编号完整范围作为候选。
- 日期页公开 RJ 先过滤掉解析成其他日期的脏条目，避免 2026 等非目标日期污染当天编号范围。
- 保留同社团公开原作边缘候选作为补偿，但主策略改回“当天范围批量 product/info 后按 maker / 特典条件筛选”。
- 策略版本提升到 `date-range-v4`，旧 `date-gap-v2/v3` 完成记录不会被复用，避免继续跳过旧漏扫结果。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\tests\test_dlsite_bonus_probe_service.py`：通过。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_dlsite_service_bulk_product_info.py -q`：通过，`17 passed`。
- 使用 `RJ01297739 / RJ01314197 / RJ01318269` 模拟 2025-01-01 当天范围：候选数 20528，已包含 `RJ01315736`。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增 `_build_range_candidates()`，日期页候选改为完整编号范围，策略版本改为 `date-range-v4`。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增当天完整范围覆盖 `RJ01315736` 的回归测试，并更新旧策略复用测试。
- `progress.md`：追加本轮候选策略校正记录，覆盖上一条记录中“同社团边缘窗口作为主修复”的不足。
- 回滚方式：还原上述服务和测试文件中本轮 `_build_range_candidates`、`DEFAULT_DATE_RANGE_LIMIT`、`date-range-v4`、`date_page_range_*` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 优化社团补全特典附赠展示
### What was done
- 社团补全作品卡片和列表行新增“商品附赠品”视觉层级，特典不再只是和本作并列显示，而是通过缩进、连接线、紫色挂靠条和“附赠于 RJ”提示表达归属。
- 展示层复用 `linked_rjcodes` 里的真实关联关系，排除当前作品 RJ 后显示原作 RJ；缺少可识别原作时降级显示“本作”，不改后端数据。
- 保持现有社团补全配色体系，浅色态沿用 violet / surface 变量，暗色态补独立兜底，避免新样式在暗色下失真。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/circle/WorkCard.vue`：特典卡片新增附赠关系计算、从属卡片边框 / 左侧挂线 / “附赠于 RJ”提示和暗色适配。
- `frontend/src/components/circle/WorkListRow.vue`：特典列表行新增附赠关系计算、缩进连接线、“附赠于 RJ”提示、移动端收窄和暗色适配。
- `progress.md`：追加本轮社团补全特典附赠展示记录。
- 回滚方式：还原上述两个组件中本轮 `bonusParentRjcode`、`is-bonus-work`、`work-bonus-relation` / `wlr-bonus-relation` 和附赠样式相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 重做社团补全特典父子附赠样式
### What was done
- 将社团补全作品视口改为“主商品 + 附赠品”分组渲染：特典不再作为顶层卡片 / 行参与平级展示，而是按 `linked_rjcodes` 归并到对应本作下面。
- 卡片模式下，主商品仍保留原作品卡；特典改成主商品底部的“附赠品”货架条，使用小封面、商品附赠品标签、标题 / RJ 和迷你操作按钮，不再复用完整作品卡。
- 列表模式下，特典改成主行下方缩进的附赠品条，带连接线和独立背景，视觉上属于本作而不是另一条平级作品。
- 补充赠品条浅色 / 暗色态、选中 / 闪烁 / 定位样式，并修正外层赠品条为非嵌套按钮结构，避免按钮内嵌按钮。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup 注释、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue progress.md`：通过。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增特典分组归并逻辑、主商品 bundle 渲染、专用附赠品条、暗色态和赠品条交互。
- `frontend/src/components/circle/WorkCard.vue`：保留特典自身关系字段和标记样式，供未能归并到本作的特典兜底展示。
- `frontend/src/components/circle/WorkListRow.vue`：保留特典自身关系字段和标记样式，供未能归并到本作的特典兜底展示。
- `progress.md`：追加本轮父子附赠样式重做记录，覆盖上一条“同级项装饰”的不足。
- 回滚方式：还原上述三个前端组件中本轮 `groupedItems`、`bonusParentCode`、`circle-work-bundle`、`circle-bonus-shelf`、`circle-bonus-gift`、`bonusParentRjcode`、`work-bonus-relation` / `wlr-bonus-relation` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 修正社团补全特典附属展示
### What was done
- 修正社团补全特典归并顺序：先基于完整作品列表按 `linked_rjcodes` 归并本作和特典，再对主作品组分页，避免本作与特典被分页拆开后回到平级卡片。
- 移除特典在 `WorkCard` / `WorkListRow` 里的平级装饰样式，删掉紫色竖条、连接线和“附赠于本作”兜底文案，避免无法归并时出现伪从属关系。
- 将本作下方的特典展示改成轻量附属条：贴在本作卡片底部 / 列表行下方，使用原页面蓝灰系变量、小“特典”标记和紧凑操作按钮，不再使用突兀的紫色货架样式。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：改为全量作品先归并、主作品组分页，并重做特典附属条为低调内嵌样式。
- `frontend/src/components/circle/WorkCard.vue`：移除平级特典卡片的附赠关系计算、`is-bonus-work` 类、紫色边框 / 左条和“附赠于本作”文案。
- `frontend/src/components/circle/WorkListRow.vue`：移除平级特典行的附赠关系计算、缩进连接线、紫色背景和“附赠于本作”文案。
- `progress.md`：追加本轮错误样式修正记录。
- 回滚方式：还原上述三个前端组件中本轮全量归并、`pagedGroups`、平级装饰删除、轻量附属条样式相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 调整社团补全特典右上角小卡
### What was done
- 将卡片模式下的特典从本作底部附属条改为右上角悬浮小卡，尺寸小于本作卡片，视觉上压在本作上表达附属关系。
- 去除特典小卡里的预览 / 外链按钮和相关图标，仅保留特典自己的入库按钮，避免无意义操作图标干扰。
- 特典小卡保留封面、特典标记和标题信息，浅色 / 暗色态继续沿用社团补全页面原有蓝灰配色变量。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue progress.md`：通过，仅有既有 LF/CRLF 提示。
- 残留扫描确认 `CircleWorksViewport.vue` 中已无 `ExternalLink`、特典预览按钮、“附赠于 / 商品附赠品 / 附赠品”旧文案残留。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：调整卡片模式特典为右上角浮层小卡，删除特典预览按钮，仅保留入库按钮。
- `progress.md`：追加本轮右上角特典小卡视觉修正记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `ExternalLink` 移除、特典预览按钮删除、`.circle-bonus-shelf.is-card` / `.circle-bonus-gift` 右上角小卡样式相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 修复社团补全特典附属归并展示
### What was done
- 修复社团补全作品列表的特典归并逻辑：后端在分页前先把特典挂到本作，避免特典因为服务端分页被切成平级卡片。
- 前端作品视口优先读取后端 onus_works，并保留当前页兜底归并；特典以小一号附属卡覆盖在本作右上角，只保留入库按钮。
- 修复特典 RJ 识别口径：canonical_rjcode 作为本作挂载点，display_rjcode / download_plan.rjcode / smr_available_rjcode 作为特典自身 RJ，避免把本作误判成自己。
- 修复定位链路：从搜索跳到特典时会跳到本作所在页，并能识别嵌套特典命中。
### Testing
- ..\.venv\Scripts\python.exe -m pytest tests/test_circle_completion_bonus_grouping.py（backend 目录执行）：2 passed。
- cd frontend; npm run build：通过，产物构建完成；仅保留现有 Rollup / lottie-web 体积与 eval 警告。
- 固定字符串残留扫描：确认特典附属卡内没有 ExternalLink、预览按钮、附赠于、商品附赠品、附赠品 等旧文案；WorkListRow.vue 仍有正常下载入口的 ExternalLink。
- git diff --check -- backend/app/core/circle_completion_service.py backend/tests/test_circle_completion_bonus_grouping.py frontend/src/components/circle/CircleWorksViewport.vue frontend/src/views/CircleCompletion.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue progress.md：通过，仅 LF/CRLF 提示。
### Notes
- ackend/app/core/circle_completion_service.py：新增特典归并、嵌套返回清理与定位父页逻辑，服务端分页前先建立本作-特典关系。
- ackend/tests/test_circle_completion_bonus_grouping.py：新增回归测试，覆盖分页前归并和特典定位到父作品页。
- rontend/src/components/circle/CircleWorksViewport.vue：读取 onus_works 渲染右上角附属小卡，并保留前端兜底归并。
- rontend/src/views/CircleCompletion.vue：让跳转定位识别嵌套特典。
- rontend/src/components/circle/WorkCard.vue：保留本作卡片本体展示，移除此前误导性的平级特典装饰。
- rontend/src/components/circle/WorkListRow.vue：保留列表行本体展示，移除此前误导性的平级特典装饰。
- 回滚方式：按本轮提交前状态回退上述文件；若只回退后端归并，需要同步回退前端 onus_works 读取，避免接口字段不一致。

## 2026-07-05 - Task: 修复真实社团特典父子归并与下载按钮
### What was done
- 修复真实数据下特典无法挂到本作的问题：后端在社团补全视图构建时，对缺少持久化父作品关系的特典按同社团、同 maker、同发售日推断父作品，并在分页前归并。
- 前端特典兜底归并优先读取 `bonus_parent_rjcode`，避免后端已经补出的父子关系在浏览器侧被忽略。
- 右上角特典小卡保留下载动作：未本地下载但有下载源时显示“下载”，已本地下载时显示入库按钮；仍不显示预览 / 外链图标。
- 已用目标社团 `リリムワークス/兎月りりむ。` / `RG62878` 的真实接口和实际页面验证，确认特典卡不再和本作平级并列。

### Testing
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_circle_completion_bonus_grouping.py`：通过，3 passed。
- `cd frontend; npm run build`：通过，产物构建完成；仅保留既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 真实接口验证：`/api/circle-completion/circles/RG62878/works?tab=missing&page=1&page_size=100&include_dl_only=true&sort=release_desc` 返回 `total=42`、`parents=17`、`topBonus=1`，不再是原先 `total=59`、`parents=0`、`topBonus=18` 的平级结构。
- 实际页面 DOM 验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 可见 `hasBonus=5`、`gifts=5`、`downloadButtons=4`、`previewButtons=0`、`externalIcons=0`；小卡坐标落在父卡右上角。
- `git diff --check -- backend/app/core/circle_completion_service.py backend/tests/test_circle_completion_bonus_grouping.py frontend/src/components/circle/CircleWorksViewport.vue frontend/src/views/CircleCompletion.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/circle_completion_service.py`：新增真实特典父作品推断、`bonus_parent_rjcode` 优先归并，并在视图状态构建后统一补父子关系。
- `backend/tests/test_circle_completion_bonus_grouping.py`：新增真实场景回归测试，覆盖特典 linked 只有自身时仍能按同发售日父作品归并。
- `frontend/src/components/circle/CircleWorksViewport.vue`：兜底归并读取 `bonus_parent_rjcode`，特典小卡新增下载 / 入库动作分流与按钮样式。
- `progress.md`：追加本轮真实数据修复与页面验证记录。
- 回滚方式：还原上述三个代码文件中本轮 `_completion_attach_bonus_parent_codes`、`bonus_parent_rjcode`、`canDownloadBonus`、`.circle-bonus-mini-action.download` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 调整社团补全特典内联放大主图
### What was done
- 删除特典详情的全屏 teleport / 遮罩展示，改为点击右上角特典小卡后在所属本作卡片上就地放大展示。
- 放大卡展示完整主宣传图、RJ、标题、发售日、社团名、来源状态和下载 / 入库按钮，不再弹出独立弹窗。
- 放大图源从列表缩略图切换为 DLsite 主宣传图：`_img_main_240x240` / `_img_sam` 会转换为 `_img_main.jpg`，小特典卡仍保留缩略图展示。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 实际页面验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 点击第一个特典后，DOM 中 `detailCount=1`、`backdropCount=0`、详情卡 `position=absolute`。
- 实际页面图片验证：详情图 `src=https://img.dlsite.jp/modpub/images2/work/doujin/RJ01570000/RJ01569983_img_main.jpg`，`object-fit=contain`，确认不是 `_img_sam` 或 `_img_main_240x240` 列表图。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增内联特典详情卡、主宣传图 URL 转换、展开层级控制、暗色 / 移动端适配，并移除全屏遮罩详情。
- `progress.md`：追加本轮特典内联放大主图记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `activeBonusDetail`、`bonusMainCoverUrl`、`circle-bonus-detail-card`、`is-detail-active` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 修正社团补全特典详情卡偏蓝
### What was done
- 将特典内联详情卡暗色态从蓝灰背景改为页面一致的中性黑灰渐变。
- 去掉详情卡阴影里的蓝色主色混合，改为纯黑透明阴影。
- 将详情卡“下载”按钮从亮蓝主按钮改成低饱和灰色按钮，避免整块视觉偏蓝。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 实际页面验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 点击特典后，详情卡背景为 `rgba(34,36,40)->rgba(24,25,29)` 中性灰渐变，下载按钮为 `rgb(91,93,99)->rgb(61,63,69)` 灰色渐变，`backdropCount=0`。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：调整特典详情卡暗色背景、边框、阴影、封面底色、meta chip 和下载按钮配色。
- `progress.md`：追加本轮详情卡偏蓝修正记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `.circle-bonus-detail-card`、`.circle-bonus-detail-action.download`、暗色态详情卡相关样式 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 对齐社团补全特典详情状态标识
### What was done
- 将特典详情卡的状态标识移到左侧主图下方空白区域，和本作卡片底部状态区的位置语义保持一致。
- 特典详情状态标识改为与本作卡片一致的 tag 体系：`未收录` 使用红色 `is-danger`，`可下载` 使用绿色 `is-success`，无源则走灰色 `is-disabled`。
- 移除右侧信息区的“下载源已匹配 / ASMR.one 可下载”来源 chip，右侧只保留日期和社团信息；详情下载 / 入库按钮改回绿色语义。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 实际页面验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 点击特典后，左侧主图下方出现 `未收录` / `可下载`，class 为 `is-danger` / `is-success`，颜色分别为红色和绿色；右侧 meta 只剩日期和社团名。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增特典详情状态 label / class 计算、左侧 media 区状态 tag、红绿灰 tag 样式和暗色适配，并调整详情下载按钮为绿色语义。
- `progress.md`：追加本轮特典详情状态标识对齐记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `bonusOwnedLabel`、`bonusDownloadLabel`、`.circle-bonus-detail-media`、`.circle-bonus-detail-tag`、详情 meta 来源 chip 删除和下载按钮绿色语义相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 还原社团补全特典详情作品信息结构
### What was done
- 删除特典详情右侧顶部重复 RJ，保留左侧信息区的 `特典 · RJ` 作为唯一 RJ 展示。
- 左侧信息区补回发售日期，格式对齐本作卡片的日期行。
- 右侧社团名 pill 改为本作卡片同款 CV 文本样式，优先读取 `cvs`，缺失时从 `maker_name` 末段兜底显示 `兎月りりむ。`，不再展示完整社团名。
- 详情动作还原为本作卡片语义：可下载时显示 `预览` 并打开原作品结构预览，本地已下载时额外显示 `入库`。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 实际页面验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 点击特典后，顶部无重复 RJ，左侧显示 `特典 · RJ01569983` 和 `2026/02/23`，右侧 CV 为蓝色 `兎月りりむ。`，无社团名 pill。
- 实际交互验证：点击详情卡 `预览` 按钮可以打开原来的下载结构预览弹窗。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增特典 CV 兜底、日期格式化、预览动作转发，删除详情顶部 RJ 和社团名 pill，并调整详情动作区为 `入库 / 预览`。
- `progress.md`：追加本轮特典详情作品信息结构还原记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `bonusCvLabel`、`bonusReleaseLabel`、`previewBonus`、`.circle-bonus-detail-cv`、`.circle-bonus-detail-linked`、详情顶部 RJ 删除和动作按钮替换相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 调整社团补全列表模式特典为平级展示
### What was done
- 社团补全作品渲染按视图模式分流：卡片模式继续把特典作为本作右上角附属小卡展示。
- 列表模式将 `bonus_works` 展开回独立作品行，并清空父行附属特典列表，避免行内继续挤出特典挂载条。
- 列表模式复用原有 `WorkListRow` 结构展示特典，保留标题、日期、状态和下载按钮，不新增额外装饰样式。

### Testing
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- 实际页面验证：`http://localhost:5556/circle-completion?circle_id=RG62878` 切到列表视图后，`listRows=15`、`rowBonusGifts=0`、`listBonusShelves=0`，特典 RJ01569983 / RJ01535561 / RJ01514221 等作为普通列表行出现。
- 实际页面回归：切回卡片视图后，`cardCells=10`、`cardBonusGifts=5`、`rowBonusGifts=0`，右上角特典小卡仍保留。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增 `displayGroups`，列表模式展开特典为平级渲染组，分页、虚拟行和图片激活逻辑改走当前模式渲染组。
- `progress.md`：追加本轮列表模式特典平级展示记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `displayGroups`、`totalItems`、`pagedGroups`、`itemViewModels.key` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 调整社团补全特典查找入口为顶部选择批量
### What was done
- 移除作品卡片 / 列表行底部的“找特典”按钮，避免单卡片动作挤在作品操作区。
- 将右上工具栏的“特典补全”改为选择感知：未选择作品时仍整社团深扫；已选择作品时显示“选中特典 N”，按选中作品的原作发售日去重后批量提交特典探测。
- `work-codes` 接口补充返回 `release_dates_by_rjcode` 和 `bonus_rjcodes`，让跨页全选后也能按选中作品取发售日，并跳过本身已经是特典的作品。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\circle_completion_service.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/core/circle_completion_service.py frontend/src/views/CircleCompletion.vue frontend/src/components/circle/CircleWorksViewport.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/circle_completion_service.py`：`list_circle_completion_work_codes()` 增加选中作品发售日映射和特典编号列表。
- `frontend/src/views/CircleCompletion.vue`：顶部特典按钮改为选择感知入口，新增选中作品发售日收集和批量提交逻辑。
- `frontend/src/components/circle/CircleWorksViewport.vue`：移除卡片 / 列表行底部找特典按钮和对应事件。
- `progress.md`：追加本轮入口调整记录。
- 回滚方式：还原上述三个文件中本轮 `release_dates_by_rjcode`、`bonus_rjcodes`、`bonusProbeActionLabel`、`getSelectedBonusProbeDates`、`startBonusProbeFromToolbar`、卡片 actions 删除相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 恢复社团补全作品默认预览按钮
### What was done
- 删除 `CircleWorksViewport` 对 `WorkCard` / `WorkListRow` 的自定义 actions slot 覆盖，让作品卡片和列表行重新使用原组件默认的 `预览 / 入库` 按钮样式。
- 清理不再使用的 `.circle-work-actions` / `.circle-work-action-btn` 样式，避免后续误复用旧的自定义按钮。
- 保留顶部特典补全选择逻辑：无勾选时整社团探测，有勾选时只按勾选 RJ 作品发售日探测。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\circle_completion_service.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/views/CircleCompletion.vue backend/app/core/circle_completion_service.py`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：移除四处自定义 actions slot 和对应 CSS，恢复 `WorkCard` / `WorkListRow` 默认操作区。
- `frontend/src/views/CircleCompletion.vue`：保留顶部特典按钮的选择分流逻辑，本轮未改变业务行为。
- `backend/app/core/circle_completion_service.py`：保留选中作品发售日映射，本轮未改变后端行为。
- `progress.md`：追加本轮默认预览按钮恢复记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮删除 actions slot / `.circle-work-actions` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 接入特典补全任务展示记录通知链路
### What was done
- 将 `circle_completion_bonus_probe` 纳入任务中心社团补全域，任务标题、来源动作、进度指标和路由统一展示为特典补全；邮件索引触发的新作探测保留 `new_release_bonus_probe` 业务动作。
- 操作历史识别特典补全 / 新作特典探测，记录发售日、探测数、命中数、写入数和请求数，前端历史列表显示对应动作文案。
- 通知系统补充特典探测的站内通知标题、摘要和 extra 统计块，完成通知可以看到发售日、探测 RJ、命中特典、写入和 DLsite 请求。
- 邮件索引新作同步后按邮件新作发售日排队特典探测任务，避免新作邮件只入索引、不触发早期特典查找。

### Testing
- `cd backend; ..\backend\venv\Scripts\python.exe -m pytest tests\test_task_notification_service.py tests\test_task_center_service.py -q`：22 passed。
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\notification_helper.py backend\app\core\task_notification_service.py backend\app\core\task_center_service.py backend\app\core\email_watcher_service.py backend\app\core\activity_log_service.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/core/notification_helper.py backend/app/core/task_notification_service.py backend/app/core/task_center_service.py backend/app/core/email_watcher_service.py backend/app/core/activity_log_service.py backend/tests/test_task_notification_service.py backend/tests/test_task_center_service.py frontend/src/views/ActivityHistory.vue`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/task_center_service.py`：补充特典探测任务中心 domain、标题、指标、来源动作归一和默认 label 过滤。
- `backend/app/core/activity_log_service.py`：将特典探测纳入社团补全操作历史并写入特典统计 detail。
- `backend/app/core/email_watcher_service.py`：邮件索引新作同步完成后按新作发售日创建特典探测任务。
- `backend/app/core/notification_helper.py`：新增特典探测通知 extra 统计和摘要。
- `backend/app/core/task_notification_service.py`：新增特典探测 / 新作特典探测站内通知文案。
- `frontend/src/views/ActivityHistory.vue`：操作历史列表识别并显示特典补全、新作特典探测动作。
- `progress.md`：追加本轮展示记录通知链路接入记录。
- 回滚方式：还原上述文件中 `CIRCLE_COMPLETION_BONUS_PROBE` 展示归类、`bonus_probe` / `new_release_bonus_probe` 文案、邮件触发 `_trigger_bonus_probe_for_new_releases()`、通知 extra 和历史动作识别相关 hunk，并删除本段进度记录。


## 2026-07-05 - Task: 优化特典补全启动后的全站延迟
### What was done
- 定位本地高延迟根因：特典补全 v4 的当天完整 RJ 范围会产生数万候选，旧实现把 `dlsite_bonus_probe_cache.rjcode.in_(5w+)` 同步跑在事件循环里，并逐批 ORM 写 cache；同时 DLsite/httpx 会把 500 个 RJ 的 product/info 超长 URL 直接写入 app.log。
- 保留当天完整候选策略，不缩小命中范围；将特典 cache 命中查询按 2000 个 RJ 分块，并放到后台线程执行，避免阻塞 FastAPI 事件循环。
- 将 product/info 探测结果 cache 写入改为 PostgreSQL 批量 upsert，并放到后台线程执行，同时走 `database_write` 资源预算。
- DLsite API 日志对批量 product/info URL 做摘要化，只记录候选数量和首尾 RJ；全局将 `httpx/httpcore` 调到 WARNING，避免 INFO 级别输出完整长 URL。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\app\core\dlsite_service.py backend\app\core\app_logging.py`：通过。
- `cd backend; ..\backend\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py tests\test_dlsite_service_bulk_product_info.py -q`：17 passed。
- `git diff --check -- backend/app/core/dlsite_bonus_probe_service.py backend/app/core/dlsite_service.py backend/app/core/app_logging.py`：通过。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：特典 cache 读写改为分块 / 后台线程 / 批量 upsert，降低大候选任务对事件循环和数据库的冲击。
- `backend/app/core/dlsite_service.py`：新增批量 product/info URL 日志摘要，错误日志也使用摘要 URL。
- `backend/app/core/app_logging.py`：将 `httpx` / `httpcore` 日志级别降到 WARNING，避免第三方请求日志刷超长 URL。
- `progress.md`：追加本轮特典补全延迟优化记录。
- 回滚方式：还原上述三个代码文件中本轮 `_load_cached_features_sync`、`_upsert_cache_features_sync`、`_format_api_url_for_log`、`httpx/httpcore` 日志级别相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 展示特典探测已查 RJ 计数
### What was done
- 特典补全任务在候选 RJ 探测阶段按批次回传 `checked_probe_count` 和 `probe_count`，缓存命中的 RJ 也计入已查数量。
- 多发售日探测时将已完成发售日的 RJ 数和当前发售日进度合并为累计计数，进度文案同步显示当前日期 `已查/总数`。
- 前端特典补全进度卡将原来的单一“探测 RJ”数量改为“已查 RJ”计数，显示 `已查 / 总数`；实时事件只有 current_step 时会从文案里的 `x/y` 兜底展示。

### Testing
- `.venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\app\core\task_engine.py`：通过。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/core/dlsite_bonus_probe_service.py backend/app/core/task_engine.py frontend/src/views/CircleCompletion.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：为特典候选 RJ 批量探测增加已查 / 总数回调，并在社团多日期任务中转换为累计计数。
- `backend/app/core/task_engine.py`：特典探测完成 summary 补充 `checked_probe_count`，完成态保持 `总数 / 总数`。
- `frontend/src/views/CircleCompletion.vue`：进度卡 RJ chip 改为 `formatBonusProbeRjProgress()` 展示已查计数，并从 current_step 兜底解析实时 `x/y`。
- `progress.md`：追加本轮特典探测已查 RJ 计数记录。
- 回滚方式：还原上述三个代码文件中本轮 `checked_probe_count`、`probe_progress_callback`、`formatBonusProbeRjProgress` 和“已查 RJ”相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 操作记录展示特典探测结果
### What was done
- 特典补全任务完成后，操作记录不再只保存数量统计；命中时会写入特典 RJ、标题、发售日、maker 和日期维度探测结果。
- 未命中特典时也会明确写入 `bonus_probe_status=miss`，操作记录详情可以区分“没查到”和“没有记录内容”。
- 操作记录详情抽屉新增“特典探测结果”业务面板，命中时显示特典内容，未命中时显示独立空态和探测统计，并适配暗色模式和移动端。
- 软件介绍文档同步说明：社团补全的特典探测结果会进入操作历史。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\activity_log_service.py backend\tests\test_activity_log_service.py`：通过。
- `cd backend; ..\backend\venv\Scripts\python.exe -m pytest tests\test_activity_log_service.py -q`：4 passed。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/core/activity_log_service.py backend/tests/test_activity_log_service.py frontend/src/composables/useActivityDetailModels.js frontend/src/components/activity/ActivityRichBlock.vue docs/INTRODUCTION.md progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/activity_log_service.py`：为特典补全操作记录写入命中 RJ 列表、命中作品信息、日期探测结果和命中/未命中状态，并补默认 `source_action=bonus_probe`。
- `backend/tests/test_activity_log_service.py`：新增特典补全命中和未命中两条生命周期日志测试。
- `frontend/src/composables/useActivityDetailModels.js`：新增 `bonusProbe` 详情模型，统一整理特典内容、统计和日期行。
- `frontend/src/components/activity/ActivityRichBlock.vue`：新增“特典探测结果”详情面板及浅色/暗色/移动端样式。
- `docs/INTRODUCTION.md`：补充社团补全特典探测结果进入操作历史的说明。
- `progress.md`：追加本轮操作记录特典结果展示记录。
- 回滚方式：还原上述四个代码文件和 `docs/INTRODUCTION.md` 中本轮 `bonus_probe` detail 字段、`bonusProbeModel`、特典探测结果面板、测试和文档说明相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 避免社团补全重复查找已判明特典
### What was done
- 后端特典探测服务新增当前策略完成日期判断：同一 maker / 发售日 / gap / 策略版本已经完成时，API 入口直接跳过，不再创建重复后台任务。
- 社团补全 `work-codes` 增加已是特典 RJ、原作已有特典 RJ、已完成特典探测发售日，前端选中批量找特典时提前跳过这些作品。
- 单社团、选中作品、左侧批量社团三个入口都处理 `already_completed` 返回，避免对已完成范围继续轮询空任务。
- 软件介绍文档补充批量找特典的跳过规则。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\app\core\circle_completion_service.py backend\app\api\routes.py backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_circle_completion_paged_view.py`：通过。
- `cd backend; ..\backend\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py tests\test_circle_completion_paged_view.py -q`：23 passed。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/core/dlsite_bonus_probe_service.py backend/app/core/circle_completion_service.py backend/app/api/routes.py backend/tests/test_dlsite_bonus_probe_service.py backend/tests/test_circle_completion_paged_view.py frontend/src/views/CircleCompletion.vue docs/INTRODUCTION.md progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增 `reusable_completed_release_dates()` / `split_reusable_release_dates()`，复用当前策略已完成日期。
- `backend/app/api/routes.py`：特典探测启动前过滤已完成日期，全跳过时返回 `already_completed`，不创建任务。
- `backend/app/core/circle_completion_service.py`：`work-codes` 返回 `has_bonus_rjcodes` 和 `completed_bonus_probe_dates`。
- `frontend/src/views/CircleCompletion.vue`：选中批量找特典跳过特典本体、已有特典原作、已查日期，并处理全跳过提示。
- `backend/tests/test_dlsite_bonus_probe_service.py`：覆盖当前策略完成日期拆分。
- `backend/tests/test_circle_completion_paged_view.py`：覆盖 `work-codes` 返回已有特典和已完成探测日期。
- `docs/INTRODUCTION.md`：补充批量找特典跳过重复深扫规则。
- `progress.md`：追加本轮避免重复查找特典记录。
- 回滚方式：还原上述文件中本轮 `reusable_completed_release_dates`、`split_reusable_release_dates`、`already_completed`、`has_bonus_rjcodes`、`completed_bonus_probe_dates` 和前端跳过提示相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 作品级特典探测状态与轻量命中索引
### What was done
- 新增原作级特典探测状态：全社团特典补全扫完后，原作会被标记为 `has_bonus` 或 `no_bonus`，后续全社团补全只挑未判明原作对应的发售日。
- 新增轻量隐藏特典命中索引：只保存社团、maker、特典 RJ 和发售日；后续同社团同日期任务会先查本地命中索引，命中后直接复用并写回社团作品，不再重新深扫 DLsite。
- 找到隐藏特典但暂时无法可靠关联到原作时，也会先保留最小命中索引，避免以后重复扫同一批 ASMR 隐藏特典。
- 前端选中作品批量找特典时新增 `已确认无特典` 跳过提示，和已有特典 / 特典本体 / 已查日期一起区分展示。
- 软件介绍文档同步说明作品级状态和轻量命中索引策略。

### Testing
- `backend\venv\Scripts\python.exe -m py_compile backend\app\models\database.py backend\app\core\dlsite_bonus_probe_service.py backend\app\core\circle_completion_service.py backend\app\api\routes.py backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_circle_completion_paged_view.py`：通过。
- `cd backend; ..\backend\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py tests\test_circle_completion_paged_view.py -q`：25 passed。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- backend/app/models/database.py backend/alembic/versions/20260702_0001_dlsite_bonus_probe.py backend/app/core/dlsite_bonus_probe_service.py backend/app/core/circle_completion_service.py backend/tests/test_dlsite_bonus_probe_service.py backend/tests/test_circle_completion_paged_view.py frontend/src/views/CircleCompletion.vue docs/INTRODUCTION.md progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/models/database.py`：新增 `DLsiteBonusOriginalProbeState` 和 `DLsiteBonusProbeHitIndex` 两个轻量表模型。
- `backend/alembic/versions/20260702_0001_dlsite_bonus_probe.py`：迁移同步创建原作探测状态表和隐藏特典命中索引表。
- `backend/app/core/dlsite_bonus_probe_service.py`：全社团日期枚举跳过已判明原作；探测流程先复用本地命中索引，扫完后写入原作状态和命中索引。
- `backend/app/core/circle_completion_service.py`：`work-codes` 返回 `no_bonus_rjcodes`，供前端选中批量跳过。
- `frontend/src/views/CircleCompletion.vue`：选中批量找特典跳过 `no_bonus` 原作并展示对应计数。
- `backend/tests/test_dlsite_bonus_probe_service.py`：覆盖 no_bonus 原作跳过和轻量命中索引复用。
- `backend/tests/test_circle_completion_paged_view.py`：覆盖 work-codes 返回 no_bonus 原作。
- `docs/INTRODUCTION.md`：补充作品级状态和本地命中索引说明。
- `progress.md`：追加本轮作品级特典探测状态与轻量命中索引记录。
- 回滚方式：还原上述文件中本轮 `DLsiteBonusOriginalProbeState`、`DLsiteBonusProbeHitIndex`、`_mark_original_probe_states_after_scan`、`_load_reusable_hidden_bonus_features`、`no_bonus_rjcodes` 和前端 `skippedNoBonusCount` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 调淡社团补全特典小卡金光
### What was done
- 社团补全卡片模式下，特典附属小卡保留在主宣传图右下角，不再贴到整张作品卡的右下角。
- 特典小卡金色提示改为更淡的边框、外晕和扫光，暗色模式下同步降低金色强度。
- 关闭特典详情卡时会自动取消该特典的选中态，避免详情关了但小卡还保持选中。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：金光已降为 `borderColor=rgba(250, 204, 21, 0.26)`，外晕为 `rgba(250, 204, 21, 0.10) 0px 0px 14px`，扫光透明度低于原强度并保留动画。
- 实际页面交互验证：点击特典小卡后详情出现且选中数为 1；点击关闭后详情消失且选中数为 0。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：调低卡片模式特典小卡金色边框、外晕、扫光和暗色态强度，并保留关闭详情取消选中逻辑。
- `progress.md`：追加本轮特典小卡金光调淡和验证记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `.circle-bonus-shelf.is-card .circle-bonus-gift`、`bonusGiftSoftGleam`、暗色态金色阴影和 `closeBonusDetail()` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 微调社团补全特典小卡金光强度
### What was done
- 将特典附属小卡金色效果从过淡状态稍微加浓，只提高边框、外晕、扫光和选中态金色透明度。
- 保持小卡仍依附在主宣传图右下角，未改动详情展示和关闭取消选中逻辑。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡数量为 6，仍位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：金色边框为 `rgba(250, 204, 21, 0.32)`，外晕为 `rgba(250, 204, 21, 0.14) 0px 0px 15px`，扫光渐变提升到 `rgba(255, 236, 153, 0.16)`。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：小幅提高卡片模式特典小卡金色边框、外晕、扫光、hover、selected 和暗色态强度。
- `progress.md`：追加本轮金光强度微调记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮金色透明度相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 加强社团补全特典小卡金色提示
### What was done
- 将特典附属小卡金色提示加浓到更明显的一档，重点提高深色模式下边框和外晕强度。
- 同步增强小卡扫光、hover 与 selected 金色反馈，保持主图右下角依附位置和详情交互不变。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡数量为 6，仍位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：暗色态金色边框为 `rgba(250, 204, 21, 0.48)`，外晕为 `rgba(250, 204, 21, 0.30) 0px 0px 22px`，扫光渐变提升到 `rgba(255, 236, 153, 0.26)`。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：提高特典小卡金色边框、外晕、扫光动画、hover、selected 和暗色态可见度。
- `progress.md`：追加本轮金色提示加浓记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮金色透明度、阴影半径和 `bonusGiftSoftGleam` 相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 增加社团补全特典稀有外圈光效
### What was done
- 参考 Steam 稀有卡片外圈效果，为特典附属小卡增加外扩金色 halo 光圈，不再只依赖卡片内部扫光。
- 卡片模式特典小卡允许外圈溢出显示，并新增轻微呼吸动画，突出“附属特典”的稀有提示。
- 深色模式下同步加强金色边框、外圈光晕和 halo 亮边，保持主宣传图右下角位置不变。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡数量为 6，仍位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：特典小卡 `overflow=visible`，外圈 `::before` 为 `inset=-6px`，动画为 `bonusGiftRareHalo`，外圈阴影为 `rgba(250, 204, 21, 0.48) 0px 0px 22px 5px`。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增特典小卡外扩金色 halo、`bonusGiftRareHalo` 动画，并强化深色模式稀有外圈样式。
- `progress.md`：追加本轮特典稀有外圈光效记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `::before` halo、`bonusGiftRareHalo`、`overflow: visible`、暗色态 halo 覆盖和增强阴影相关 hunk，并删除本段进度记录。

## 2026-07-05 - Task: 收窄社团补全特典外圈光效
### What was done
- 去掉特典小卡过宽的 conic 金环，改为 2px 外扩的窄金色亮边。
- 保留特典稀有感，但把大面积黄色光圈压成细边和轻外晕，避免遮住封面观感。
- 深色模式下同步改成窄亮边，主宣传图右下角定位和详情交互不变。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡数量为 6，仍位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：特典小卡 `overflow=visible`，外圈 `::before` 为 `inset=-2px`，背景已改为线性金色亮边，外圈阴影为 `rgba(250, 204, 21, 0.42) 0px 0px 12px 2px`。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：将特典小卡 halo 从宽金环改为窄金色亮边，降低阴影扩散半径并保留轻微呼吸动画。
- `progress.md`：追加本轮收窄特典外圈光效记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `::before inset`、halo 背景、box-shadow、暗色态 halo 和 `bonusGiftRareHalo` 缩放幅度相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 去除社团补全特典小卡相框感
### What was done
- 去掉特典小卡完整金色外框感，不再使用连续线性边框和硬描边阴影。
- 将外层效果改为右上、左下和中心的局部金色柔光，保留稀有感但不形成一圈框。
- 深色模式同步改为局部光斑和柔和外晕，主宣传图右下角定位不变。

### Testing
- 实际页面 `http://localhost:5556/circle-completion?circle_id=RG62878` 验证：特典小卡数量为 6，仍位于主宣传图右下角，`insideCoverBottom=true`、`insideCoverRight=true`、`nearCoverBottom=true`、`nearCoverRight=true`。
- 实际页面 DOM 样式验证：外层 `::before` 改为多段 radial 局部光斑，`filter=blur(1.6px)`，主阴影不再包含 `0 0 0 1px` 硬描边。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：移除特典小卡完整金色框线效果，改为局部金色柔光和低强度外晕。
- `progress.md`：追加本轮特典小卡去框化记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `::before` radial 光斑、border-color、box-shadow、暗色态局部光效相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 去掉社团补全特典文字灰底
### What was done
- 撤回本轮误加到本体作品卡片的 `immersive` 相关改动，本体作品卡片恢复原结构。
- 去掉特典附属小卡右下角“特典”文字背后的深灰胶囊底，改为透明文字浮层。
- 保留白字、细描边和轻投影，避免在图片上完全看不清。

### Testing
- `rg -n "immersive|work-card--immersive" frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/CircleWorksViewport.vue`：无残留。
- `rg -n "background: rgba\\(15, 23, 42, 0\\.64\\)" frontend/src/components/circle/CircleWorksViewport.vue`：无残留。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：将 `.circle-bonus-gift-badge` 改为透明背景，并保留文字描边和阴影。
- `progress.md`：追加本轮灰底移除和本体卡片恢复记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中 `.circle-bonus-gift-badge` 本轮背景改动；如需恢复误加的沉浸式本体卡片，可从本轮前的 diff 反向恢复 `immersive` 相关 hunk，但默认不建议恢复。

## 2026-07-06 - Task: 清除社团补全特典小卡底部深灰边
### What was done
- 卡片模式特典小卡的按钮背景改为透明，避免深色模式下按钮底色从图片底部露出。
- 卡片模式特典小卡的封面层改为绝对铺满整个按钮，并把封面层背景改为透明。
- 深色模式下单独覆盖卡片模式特典小卡和封面层背景为透明，不影响列表模式特典行。

### Testing
- `rg -n "circle-bonus-shelf\\.is-card \\.circle-bonus-gift|circle-bonus-shelf\\.is-card \\.circle-bonus-gift-cover|background: transparent" frontend/src/components/circle/CircleWorksViewport.vue`：确认卡片模式小卡和封面层均有透明背景覆盖。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：让卡片模式特典小卡图片层铺满按钮，并清除按钮与封面层的深灰背景。
- `progress.md`：追加本轮清除特典小卡底部深灰边记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `.circle-bonus-shelf.is-card .circle-bonus-gift`、`.circle-bonus-shelf.is-card .circle-bonus-gift-cover` 和暗色态透明背景覆盖相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 完善 DLsite ASMR 特典探测调度与完成口径
### What was done
- 将特典探测的发售日完成口径改为“同发售日所有原作都有 `has_bonus/no_bonus` 结论”，避免把 500RJ 批次完成误当作日期完成。
- 本地隐藏特典命中线索改为优先确认但不直接跳过整天；命中后继续补完同日未判明原作。
- 日期调度改为先处理本地命中线索，再按最早 / 最晚两端向中间推进。
- DLsite 日期页、公开作品确认、候选 RJ 探测出现异常或扫描范围超预算时，不再写 `no_bonus`，只允许沉淀已经确认的命中线索。
- `request_count` 改为 DLsite 批量请求次数，`checked_probe_count` 继续表示已确认 RJ 数，并把原作结论统计写入任务元数据。
- 新增 `docs/dlsite-bonus-probe.md` 固化特典探测完成口径、调度规则、异常规则和进度字段。

### Testing
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-postgresql.ps1 -StartOnly`：通过，PostgreSQL 已启动，配置健康。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; @'...create_postgres_test_engine...'@ | .\venv\Scripts\python.exe -`：通过，测试库 `kikoerumanager_test` 返回 `select 1`。
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py app\core\task_engine.py app\api\routes.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py -q --maxfail=1 --basetemp=.pytest-codex-bonus-probe-manual`：通过，22 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。
- `git diff --check -- backend/app/core/dlsite_bonus_probe_service.py backend/app/core/task_engine.py backend/app/api/routes.py backend/tests/test_dlsite_bonus_probe_service.py`：通过，仅 LF/CRLF 提示。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：修正请求计数、发售日完成复用、日期调度、本地线索续扫、异常不产出 `no_bonus` 和原作结论统计。
- `backend/app/core/task_engine.py`：特典探测任务 summary 增加原作结论统计字段。
- `backend/app/api/routes.py`：启动特典探测时用 `circle_id` 参与完成日期复用判断，避免旧日期状态跳过未结论原作。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增 500RJ 请求计数、本地线索调度、未结论原作不跳过、异常不写 `no_bonus` 的回归测试。
- `docs/dlsite-bonus-probe.md`：新增 DLsite ASMR 特典探测开发说明。
- `progress.md`：追加本轮特典探测调度完善记录。
- 回滚方式：还原上述代码 / 测试 / 文档文件中本轮关于特典探测调度、完成口径、异常保护和进度字段的改动；删除本段进度记录。

## 2026-07-06 - Task: 防止同日特典探测 RJ range 重复查询
### What was done
- 为 DLsite 特典候选 RJ 增加按数字排序的 range shard，每个 shard 带 `range_key`、起止 RJ 和数量。
- 增加进程内 active lease，同一发售日被多个调度来源同时命中时，后进入的探测会跳过正在查询的 RJ，避免重复请求同一格。
- 候选请求结束后在 `finally` 释放 lease，异常路径也不会永久占住 RJ。
- 特典探测结果中保留 shard 摘要，方便后续排查同日并发是否覆盖了正确 RJ 区间。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py -q --maxfail=1 --basetemp=.pytest-codex-bonus-probe-range-lease`：通过，25 passed；仅有既有 deprecation warning 和 `.pytest_cache` 写入 warning。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增 candidate shard range key、active lease、释放逻辑，并让 `probe_date()` 使用 lease 后再请求候选 RJ。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增同日重复 lease 被 active RJ 拦截、释放后可重新分片的回归测试。
- `docs/dlsite-bonus-probe.md`：补充同一发售日并发命中时必须按 RJ range shard lease 的规则。
- `progress.md`：追加本轮 range 去重记录。
- 回滚方式：还原上述文件中本轮 candidate shard active lease、测试和文档说明相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 简化 DLsite 特典探测为 6 并发日期调度
### What was done
- 将 DLsite 特典探测默认并发从 5 调整为 6，并同步 API 请求模型与任务执行默认值。
- 移除“本地线索优先 + 最早 / 最晚两端推进”的日期调度策略，改为按每个发售日的最小原作 RJ 升序排序。
- `probe_circle_dates()` 改为 6 个日期 worker 并发消费发售日队列；每个 worker 领取一个发售日后完整跑完该发售日，再领取下一个。
- 保留 RJ range active lease，继续防止同一发售日在重复触发或并发 worker 下重复请求同一 RJ 格子。
- 更新 DLsite 特典探测开发说明，明确 6 并发、最小 RJ 排序和单日期完整执行规则。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py -q --maxfail=1 --basetemp=.pytest-codex-bonus-probe-six-workers`：通过。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：默认并发改为 6，日期排序改为最小原作 RJ 升序，发售日处理改为 6 worker 并发队列。
- `backend/app/core/task_engine.py`：特典探测任务默认并发改为 6。
- `backend/app/api/routes.py`：特典探测启动请求默认并发改为 6。
- `backend/tests/test_dlsite_bonus_probe_service.py`：更新日期排序测试，并新增 6 日期 worker 并发回归测试。
- `docs/dlsite-bonus-probe.md`：同步新的调度口径。
- `progress.md`：追加本轮 6 并发调度简化记录。
- 回滚方式：还原上述文件中本轮默认并发、日期排序、worker 队列、测试和文档说明相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 收束社团补全特典小卡金色发光
### What was done
- 去掉卡片模式特典小卡外层完整金色环边，避免视觉上变成一圈黄光晕。
- 将特典小卡金色效果收束到贴边小范围柔光和轻微斜向闪光，保留附赠品的稀有感但降低黄色浓度。
- 同步调整深色模式下的特典小卡发光强度，只影响卡片模式特典小卡，不改本体作品卡片和列表模式特典行。

### Testing
- 使用 in-app browser 打开 `http://localhost:5556/circle-completion?circle_id=RG62878` 实测：特典小卡存在，`::before` 外层边框宽度为 `0px`，背景不再是完整环形黄雾。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：收束卡片模式特典小卡的金色发光、动画透明度和深色态发光强度。
- `progress.md`：追加本轮特典小卡金色发光收束记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `.circle-bonus-shelf.is-card .circle-bonus-gift`、伪元素、`bonusGiftRareHalo` / `bonusGiftSoftGleam` 和暗色态相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 增强社团补全特典小卡呼吸发光
### What was done
- 给卡片模式特典小卡增加边缘亮度呼吸动画，让金色柔光有周期性明暗变化。
- 给特典小卡伪元素增加局部光点与背景位置变化，让效果更灵动一点，但不扩大成整圈黄光晕。
- 加强斜向闪光的位移和透明度变化，并补齐深色模式下的背景尺寸覆盖，保证暗色态动画也生效。

### Testing
- 使用 in-app browser 打开 `http://localhost:5556/circle-completion?circle_id=RG62878` 实测：特典小卡 `animationName` 为 `bonusGiftCardBreath`，伪元素透明度、背景位置、边框颜色和阴影在 900ms 采样间有变化。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：为卡片模式特典小卡增加呼吸发光、局部光点移动和深色态背景尺寸覆盖。
- `progress.md`：追加本轮特典小卡呼吸发光记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮 `bonusGiftCardBreath`、`bonusGiftRareHalo`、`bonusGiftSoftGleam`、小卡动画和暗色态背景尺寸相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 加强社团补全特典小卡呼吸发光强度
### What was done
- 提高卡片模式特典小卡呼吸动画的峰值亮度，并把动画周期从 3.6s 缩短到 2.8s，让亮暗变化更容易被注意到。
- 增强局部金色光点、白色闪点和斜向闪光的透明度与位移幅度，但继续保持 `inset: -2px`，避免重新变成大范围黄光晕。
- 同步提高深色模式下的金色柔光强度，使暗色页面里特典附属卡片更明显。

### Testing
- 使用 in-app browser 打开 `http://localhost:5556/circle-completion?circle_id=RG62878` 实测：峰值阴影约 `0.32 / 18px`，低谷约 `0.16 / 10px`，斜向闪光透明度在约 `0.36` 到 `0.84` 间变化。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：加强卡片模式特典小卡的呼吸峰值、局部光点、斜向闪光和深色态柔光。
- `progress.md`：追加本轮特典小卡发光强度加强记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 中本轮呼吸动画时长、透明度、阴影、渐变强度和深色态覆盖相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 修复选中查特典误报已有特典
### What was done
- 修正选中作品查特典的跳过口径，不再把原作裸 `has_bonus=True` 直接当作“已有特典”。
- 后端 `has_bonus_rjcodes` 改为先按页面同口径挂载特典子项，只有实际存在 `bonus_works` 的原作才返回“已有特典”。
- 前端本地预判同步改为只认实际挂载的 `bonus_works`，避免页面没有特典小卡却提示“已有特典”。
- 增加回归测试覆盖：原作 `has_bonus=True` 但没有特典子项时不跳过；补入真实特典子项后才跳过。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py tests\test_circle_completion_paged_view.py`：通过。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1 --basetemp=.pytest-codex-circle-bonus-has-card`：通过，7 passed；仅有既有 deprecation / pytest cache warning。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `cmd /c start-all.bat`：已按项目规则重启本地服务，前后端重新加载修复后的代码。

### Notes
- `backend/app/core/circle_completion_service.py`：让 `list_circle_completion_work_codes()` 的 `has_bonus_rjcodes` 对齐页面特典挂载口径。
- `backend/tests/test_circle_completion_paged_view.py`：新增孤立 `has_bonus` 不算已有特典、真实挂载特典才算已有特典的回归断言。
- `frontend/src/views/CircleCompletion.vue`：选中查特典本地预判改为检查实际 `bonus_works`。
- `progress.md`：追加本轮误报修复记录。
- 回滚方式：还原上述文件中本轮 `has_bonus_rjcodes`、`hasAttachedBonusWorks()` 和测试断言相关 hunk，并删除本段进度记录。

## 2026-07-06 - Task: 修复选中作品特典探测预算超限失败
### What was done
- 修正 DLsite 特典探测在 RJ 范围超出预算时直接抛异常的问题；现在会记录为 `incomplete`，保留已沉淀命中线索，但不写 `no_bonus`，整轮任务继续完成并提示未产出结论的发售日数量。
- 选中作品触发特典探测时，前端按发售日传入选中的本体 RJ；后端以这些 RJ 为锚点构造邻近候选，不再被同一天其它公开 RJ 的巨大跨度拖进整日全范围探测。
- 单作品 / 选中作品入口并发参数从 5 统一为 6，并继续使用 500RJ 批量请求单位。
- 任务中心和前端完成提示增加 `incomplete_count`，有预算超限日期时显示 warning，而不是把任务打成失败或伪装成完全完成。
- 更新 DLsite 特典探测文档，固化选中 RJ 锚点、预算超限 `incomplete`、进度字段口径。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py app\core\task_engine.py app\api\routes.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; $env:PYTHONPATH=(Get-Location).Path; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py -q --maxfail=1 --basetemp=.pytest-codex-bonus-probe-selected-scope`：通过，28 passed；仅有既有 deprecation / pytest cache warning。
- `cd frontend; npm run build`：通过。仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增选中 RJ 锚点候选构造、预算超限 `incomplete` 返回、汇总 `incomplete_count`。
- `backend/app/core/task_engine.py`：把选中 RJ 映射传入探测服务，并在任务完成文案 / summary 中保留预算超限提示。
- `backend/app/api/routes.py`：特典探测启动接口接收并规范化 `selected_rjcodes_by_date`，业务 key 区分不同选中范围。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增预算超限不失败、选中 RJ 锚点避开整日大范围并命中特典的回归测试。
- `frontend/src/views/CircleCompletion.vue`：选中作品特典探测传入按发售日分组的 RJ，并发统一为 6，完成提示支持 `incomplete_count`。
- `docs/dlsite-bonus-probe.md`：补充选中 RJ 锚点、预算超限 `incomplete` 和进度字段说明。
- `progress.md`：追加本轮预算超限失败修复记录。
- 回滚方式：还原上述文件中本轮 `selected_rjcodes_by_date`、`_build_anchor_edge_candidates()`、`incomplete_count`、预算超限返回和前端并发 / 提示相关 hunk，并删除本段进度记录。
## 2026-07-06 - Task: 修复特典探测操作记录不显示
### What was done
- 修复操作记录 lite 列表误过滤社团补全特典探测任务的问题；普通社团索引生命周期行继续隐藏，`bonus_probe` / `new_release_bonus_probe` 生命周期行保留展示。
- 为社团补全特典探测 lite 行补充精简 `detail.source_action` 和命中 / 写入 / 探测数量 chip，避免前端无法识别为“特典补全”。
- 用真实数据库确认最近的 `source_action=bonus_probe` 记录会被新过滤条件选出。

### Testing
- `.venv\Scripts\python.exe -m py_compile backend/app/api/routes.py backend/app/core/activity_log_lite.py backend/tests/test_activity_log_lite_has_children.py`
- 在 `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests/test_activity_log_lite_has_children.py tests/test_activity_log_service.py -q`，结果 `19 passed`。
- 使用项目虚拟环境查询真实 PostgreSQL，确认最近 `circle_completion/task_finished/source_action=bonus_probe` 记录存在，并在新 lite 过滤条件下返回。

### Notes
- `backend/app/api/routes.py`：调整操作记录 lite SQL 过滤，保留特典探测生命周期行。
- `backend/app/core/activity_log_lite.py`：为特典探测行补充展示 chip 和精简 detail。
- `backend/tests/test_activity_log_lite_has_children.py`：新增特典探测 lite 行回归测试。
- 回滚方式：还原以上三个文件的本轮改动；已有数据库中的操作记录无需回滚。
## 2026-07-06 - Task: 优化操作记录特典探测详情暗色样式与特典卡片
### What was done
- 修复操作记录详情里特典探测结果在暗色模式下白底、深蓝文字不可读的问题，暗色选择器同时覆盖 `html.dark` 与 `kikoerumanager-dark`。
- 将特典命中项从单行文字条改成带封面的作品卡片；封面缺失或加载失败时显示图标占位。
- 特典命中项的来源信息改为优先显示社团名，不再在详情卡里展示 `maker RGxxxx`。
- 后端新写入的特典命中详情补充 `circle_name` 与 `cover_url`，旧记录前端用 RJ 号兜底生成 DLsite 封面。
- 重启项目时检测到 PostgreSQL 进程存在但无响应，已由 `start-all.bat` 自动重启 PostgreSQL 并恢复数据库连接。

### Testing
- `.venv\Scripts\python.exe -m py_compile backend/app/core/activity_log_service.py`
- `frontend/` 下执行 `npm run build`，构建通过。
- 重启 PostgreSQL 后，使用项目虚拟环境查询真实库 `ActivityLog.count()` 返回 `3502`，确认数据库连接恢复。
- 在 `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests/test_activity_log_service.py tests/test_activity_log_lite_has_children.py -q`，结果 `19 passed`。
- `git diff --check -- frontend/src/components/activity/ActivityRichBlock.vue frontend/src/composables/useActivityDetailModels.js backend/app/core/activity_log_service.py progress.md` 通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/components/activity/ActivityRichBlock.vue`：重做特典探测结果暗色样式、状态徽章、封面卡片与社团名展示。
- `frontend/src/composables/useActivityDetailModels.js`：为特典命中项补充社团名和封面 URL 兜底。
- `backend/app/core/activity_log_service.py`：新写入的特典命中项补充社团名与封面 URL。
- `progress.md`：追加本轮修改和验证记录。
- 回滚方式：还原以上四个文件的本轮改动；若只回滚前端视觉，保留后端 `cover_url/circle_name` 字段不会影响旧页面。
## 2026-07-06 - Task: 修正操作记录特典卡片灰底暗色样式
### What was done
- 修复操作记录详情弹窗通过 Teleport 挂到 `body` 下，导致之前 `#app .activity-detail-panel` 暗色选择器无法命中的问题。
- 将特典命中卡片改为与面板融合的透明黑底，不再使用灰色独立底。
- 将特典状态、统计指标、日期 pill、RJ chip 统一改为深底白字，避免浅色 badge 插在暗色弹窗里。
- 使用 Playwright 实际打开 `http://localhost:5556/activity-history`，强制暗色主题并点开最新特典补全记录，确认计算样式已生效：特典卡片背景为透明、标题为白色、指标/日期为深底白字。

### Testing
- `frontend/` 下执行 `npm run build`，构建通过。
- `git diff --check -- frontend/src/dark-mode.css frontend/src/components/activity/ActivityRichBlock.vue frontend/src/composables/useActivityDetailModels.js backend/app/core/activity_log_service.py progress.md` 通过，仅有既有 LF/CRLF 提示。
- Playwright 实测详情弹窗：`.bonus-work-item` 背景 `rgba(0, 0, 0, 0)`，文字 `rgb(245, 247, 251)`；`.bonus-work-name` 文字 `rgb(255, 255, 255)`；统计和日期 pill 背景 `rgb(16, 17, 22)`。

### Notes
- `frontend/src/dark-mode.css`：补充 Teleport 弹窗可命中的全局暗色覆盖。
- 回滚方式：移除本轮追加的 `activity-detail-panel` 特典探测暗色覆盖块即可。
## 2026-07-06 - Task: 修正特典探测未找到记录的失败样式与详情灰底
### What was done
- 将社团补全特典探测的 `miss` / 预算超限未产出结论从展示层的失败态改为信息态；列表和详情标题显示“未找到特典”或“特典补全未完成”，不再显示失败红色。
- 特典探测详情模型补充 `hit / miss / incomplete` 三态文案，空态改为按状态显示“未找到”或“未产出无特典结论”。
- 去掉操作记录详情头部浅色渐变、关键字段行、统计块和特典空态的白底 / 灰底残留，暗色模式下统一为黑底白字并与弹窗融合。
- 实际打开 `http://localhost:5556/activity-history` 验证 20:38 的特典补全预算超限记录：列表行为 `tone-info`，详情标题为“特典补全未完成”，详情头部背景为 `rgb(11, 12, 16)` 且无渐变，页面文本不含“失败”。

### Testing
- `frontend/` 下执行 `npm run build`，构建通过；仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check` 通过；仅有既有 LF/CRLF 提示。
- 使用内置浏览器实际验证操作记录页：20:38 特典补全记录 class 为 `activity-log-row tone-info`；详情头部计算样式 `backgroundColor=rgb(11, 12, 16)`、`backgroundImage=none`；详情标题为“特典补全未完成”，未显示失败文案。
- 当前详情完整内容接口加载停在“详情加载中…”，页面日志有 `/notifications/unread-count` 与 `/watcher/status` 超时；本轮已验证列表和详情头部，完整富内容块依赖后端详情接口恢复后再目测。

### Notes
- `frontend/src/views/ActivityHistory.vue`：特典探测行的有效状态和列表动作文案改为按 `bonus_probe_status` / 预算超限语义显示。
- `frontend/src/composables/useActivityDetailModels.js`：详情页有效状态和特典探测模型增加未完成结论文案。
- `frontend/src/components/activity/ActivityRichBlock.vue`：特典探测结果组件使用模型提供的标题、空态和三态 class。
- `frontend/src/dark-mode.css`：补充操作记录详情头部、关键字段、统计块和特典空态暗色覆盖。
- `progress.md`：追加本轮修改和验证记录。
- 回滚方式：还原上述四个前端文件中本轮 `bonusProbeDisplayState`、`incomplete` 文案、`activity-detail-panel` 暗色覆盖相关 hunk，并删除本段进度记录。
## 2026-07-06 - Task: 卡片模式合并本体与特典缺失状态
### What was done
- 社团补全作品分页新增 `view_mode=card` 分支，只在卡片模式按“本体 + 特典”整组决定归属；列表模式继续走原有过滤与拆分逻辑。
- 卡片模式下只要本体或特典任意一项已拥有，整组留在“已满足”页；缺失的那一侧打 `completion_card_dimmed`，前端显示为灰色。
- 本体和特典都没拥有时，整组仍留在“缺失作品”页，并保持彩色展示。
- 前端只在当前 `viewMode === 'card'` 时请求 `view_mode=card`，列表模式请求 `view_mode=list`，并把缓存 key 按视图模式隔离。
- 已用 `start-all.bat` 重启项目，让后端新接口逻辑实际生效。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend/app/core/circle_completion_service.py backend/app/api/routes.py`：通过。
- 在 `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests/test_circle_completion_bonus_grouping.py -q`：通过，6 passed；仅有既有 deprecation / pytest cache warning。
- `frontend/` 下执行 `npm run build`：通过；仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。
- 实际请求本地接口验证 `RG62878`：`view_mode=card&tab=owned` 返回本体 `RJ01385196 owned=True dim=False`，其缺失特典 `RJ01416572 owned=False dim=True`；`view_mode=card&tab=missing` 中本体和特典都缺失的组 `dim=False`；`view_mode=list` 不返回 `completion_card_dimmed`。

### Notes
- `backend/app/core/circle_completion_service.py`：新增卡片模式整组过滤和灰化状态字段。
- `backend/app/api/routes.py`：作品分页接口透传 `view_mode`。
- `backend/tests/test_circle_completion_bonus_grouping.py`：覆盖本体有特典缺、特典有本体缺、两个都缺三种卡片模式分组。
- `frontend/src/api/index.js`：作品分页请求支持 `view_mode`。
- `frontend/src/views/CircleCompletion.vue`：按当前视图模式传参并隔离缓存。
- `frontend/src/components/circle/WorkCard.vue`：本体卡片灰化只处理封面图。
- `frontend/src/components/circle/CircleWorksViewport.vue`：卡片模式右下角特典小卡支持灰化，列表模式不加灰化 class。
- `progress.md`：追加本轮修改和验证记录。
- 回滚方式：还原上述文件中 `view_mode`、`_filter_completion_items_for_card_tab()`、`completion_card_dimmed`、卡片灰化样式和测试相关 hunk，并删除本段进度记录。
## 2026-07-06 - Task: 调整卡片模式特典灰化透明度
### What was done
- 将卡片模式右下角特典小卡的缺失灰化从半透明效果改为不透明灰阶效果，避免图片发虚不好辨认。
- 保留灰色缺失语义，只降低饱和度和亮度，不再明显透出下层内容。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅出现既有 Rollup pure annotation、lottie eval 和大 chunk 体积警告。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue progress.md`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：调整 `.circle-bonus-gift.is-dimmed` 的 `filter` 和 `opacity`。
- `progress.md`：追加本轮视觉微调记录。
- 回滚方式：还原本轮 `.circle-bonus-gift.is-dimmed` 灰化参数，并删除本段进度记录。
## 2026-07-07 - Task: 修复社团补全本地库存拥有态漏识别
### What was done
- 修复库存索引 RJ 查询只依赖 `rjcode` 列的问题；当精确列查不到时，会用目录名、相对路径、绝对路径里的完整 RJ 号做兜底命中。
- 兜底命中增加 RJ 边界过滤，避免 `RJ01627612` 误匹配到 `RJ016276120` 这类相邻编号。
- 修复库存浏览全局搜索把 `page_cursor` 传给 `global_search_files` 时后端 500 的参数不匹配问题，并让普通浏览分支也透传分页游标。
- 增加回归测试覆盖“目录名有 RJ，但索引 rjcode 列缺失”的社团补全本地拥有态识别场景。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\library_index\snapshot_store.py app\core\library_manager.py app\api\routes.py`：通过。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py -q`：通过，23 passed。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q`：通过，4 passed。

### Notes
- `backend/app/core/library_index/snapshot_store.py`：为 `find_by_rjcode()` 增加路径 RJ 兜底查询与边界过滤。
- `backend/app/core/library_manager.py`：`global_search_files()` 增加 `page_cursor` 参数并透传到普通搜索路径。
- `backend/app/api/routes.py`：库存浏览普通分支透传 `page_cursor`。
- `backend/tests/test_library_index_self_mutation.py`：新增路径 RJ 兜底命中的回归测试。
- `progress.md`：追加本轮修复和验证记录。
- 回滚方式：还原上述四个代码/测试文件中本轮 RJ 兜底与 `page_cursor` 相关 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 改为修复库存索引 RJ 字段缺失源头
### What was done
- 撤回查询层按路径兜底返回的方案，保留 `find_by_rjcode()` 对 `library_index_entries.rjcode` 的精确查询语义。
- 在库存索引写入层补齐 RJ 字段：`IndexEntry.rjcode` 缺失时，从安全化后的名称、相对路径、绝对路径提取 RJ 后再落库，避免新索引行继续漏写。
- 为旧索引脏数据增加小范围回填：精确 RJ 查询 0 命中时，只修正同 RJ、同库存范围内 `rjcode` 为空的索引行，然后再次走精确列查询。
- 调整回归测试，覆盖新写入缺 RJ 自动补齐、旧索引行缺 RJ 自动修正两种场景。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\library_index\snapshot_store.py app\core\library_manager.py app\api\routes.py`：通过。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py -k "rjcode" -q`：通过，3 passed。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q`：通过，4 passed。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py -q --basetemp=.pytest-codex-rj-repair`：通过，24 passed。

### Notes
- `backend/app/core/library_index/snapshot_store.py`：索引入库前补齐 RJ 字段，并对旧缺失 RJ 行做写回修复后再精确查询。
- `backend/tests/test_library_index_self_mutation.py`：替换查询兜底测试，新增写入补齐和旧数据回填测试。
- `progress.md`：追加本轮方案修正和验证记录。
- 回滚方式：还原本轮 `snapshot_store.py` 中 `_database_safe_entry()` RJ 补齐和 `_repair_missing_rjcode_rows()` 相关 hunk，恢复测试文件对应 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 修复特典刷新拥有态后卡片不变色
### What was done
- 修复“刷新状态”任务只更新 `CircleWork.has_kikoeru`，但没有把本次库存索引命中的拥有态同步写入 `LibraryOwnedWork` 快照的问题。
- 刷新任务现在会把选中 RJ 的 `local_owned / owned_paths / kikoeru_found_rjcodes` 写回拥有态快照；ready 索引可用且当前查不到时会清理旧快照，保证刷新状态反映当前库存。
- 修复特典详情卡在刷新后继续引用旧 bonus 对象的问题；列表数据更新后会按 RJ 替换为新的特典对象，详情里的已收录/未收录标签同步变色。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py`：通过。
- `backend/` 下执行 `$env:PYTHONPATH=(Get-Location).Path; ..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q`：通过，4 passed。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `backend/app/core/circle_completion_service.py`：刷新选中作品时同步写入/清理 `LibraryOwnedWork` 拥有态快照。
- `frontend/src/components/circle/CircleWorksViewport.vue`：刷新后按 RJ 替换展开中的特典详情对象，避免详情卡保留旧状态。
- `progress.md`：追加本轮修复和验证记录。
- 回滚方式：还原上述两个代码文件本轮 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 调整社团补全卡片模式特典灰态规则
### What was done
- 将卡片模式的灰态判断改成以当前实际挂载的特典子项为准；只要本体卡片渲染时带有特典子项，本体封面不再被 `completion_card_dimmed` 压灰。
- 特典附属小卡不再使用后端旧灰态字段，避免“实际已有特典但小卡仍然灰掉”的视觉误判。
- `WorkCard` 增加外层灰态覆盖入口，默认仍兼容旧字段，只有社团补全卡片模式按特典挂载关系覆盖。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/circle/WorkCard.vue`：新增 `completionDimmed` 覆盖入参，灰态 class 改为读统一计算值。
- `frontend/src/components/circle/CircleWorksViewport.vue`：卡片模式按 `bonus_works` 实际挂载状态动态取消本体灰态，并移除特典小卡灰态绑定和无用样式。
- `progress.md`：追加本轮样式规则调整和验证记录。
- 回滚方式：还原上述两个前端组件本轮 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 修正特典灰态按库存拥有态判断
### What was done
- 修正上一轮“有特典关系就不灰”的判断，改为“库存实际拥有特典才不灰”。
- 卡片模式下如果本体挂载了特典子项但这些特典都没有库存拥有态，本体卡片保持灰态，用来区分库存没有特典的情况。
- 特典详情卡的“已收录 / 未收录”与灰态判断复用同一个拥有态函数，避免文字和视觉状态不一致。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增 `isBonusOwned()` / `hasOwnedRenderedBonus()`，灰态改为按挂载特典的库存拥有态计算。
- `progress.md`：追加本轮规则修正和验证记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 本轮拥有态判断 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 修正特典卡片刷新后的组内灰态规则
### What was done
- 纠正上一轮把灰态理解成“特典自身未拥有就灰”的错误，恢复为本体与特典同组对比：组内至少一边已拥有时，缺失的那一边才灰；组内都未拥有时都保持彩色。
- 本体卡片灰态现在按“特典有、本体没有”动态计算；特典小卡灰态按“本体有、该特典没有”动态计算。
- 灰态直接读取刷新后的 `server_owned / owned / completion_owned / local_owned`，避免刷新特典拥有状态后小卡仍沿用旧 `completion_card_dimmed`。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增组内拥有态判断，`shouldDimWorkCard()` 和 `shouldDimBonusCard()` 都按当前渲染组实时计算。
- `progress.md`：追加本轮业务规则纠正和验证记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 本轮组内灰态判断 hunk，并删除本段进度记录。
## 2026-07-07 - Task: 优化社团补全卡片灰态计算效率
### What was done
- 将卡片模式的本体拥有态、组内拥有态、本体灰态、特典小卡灰态提前计算进 `itemViewModels`，避免模板渲染时反复扫描同一组特典。
- 特典小卡新增预计算 view model，复用 key、选中态、闪烁态、定位态、拥有态和灰态，减少 class 绑定里的重复函数调用。
- 图片可见队列改为复用特典小卡预计算 key，减少滚动渲染时重复拼接 key。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：卡片模式灰态和特典小卡状态改为 view model 预计算。
- `progress.md`：追加本轮性能优化和验证记录。
- 回滚方式：还原 `frontend/src/components/circle/CircleWorksViewport.vue` 本轮 view model 预计算相关 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 校正特典探测日期并发测试策略
### What was done
- 按当前发布策略保留 DLsite 特典探测默认 6 并发，不再把日期 worker 测试固定到保守 2 并发。
- 更新特典探测日期并发测试名称和断言，让测试表达“按配置使用 6 个日期 worker”的行为。
- 复核 Docker 单镜像 Redis 依赖已写入 `Dockerfile` 和 `docker/entrypoint.sh`，Docker 导入文件镜像版本已更新到 `1.6.72`。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests/test_dlsite_bonus_probe_service.py::test_probe_circle_dates_uses_configured_date_workers tests/test_routes_maintenance_config.py::test_redis_and_bonus_probe_defaults_use_parallel_probe_workers tests/test_routes_maintenance_config.py::test_update_config_validates_redis_and_bonus_probe -q --basetemp .pytest-codex-release-v172-fix3`：通过，3 passed。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests/test_redis_config.py tests/test_resource_budget_service.py tests/test_dlsite_bonus_probe_service.py tests/test_circle_completion_bonus_grouping.py tests/test_circle_completion_paged_view.py tests/test_baidu_netdisk_service.py tests/test_http_download_service.py tests/test_task_notification_service.py tests/test_routes_maintenance_config.py -q --basetemp .pytest-codex-release-v172-full`：通过，257 passed。
- `frontend/` 下此前已执行 `npm run build`：通过，仅有既有 chunk size / lottie eval warning。

### Notes
- `backend/tests/test_dlsite_bonus_probe_service.py`：特典日期探测并发测试改为验证配置的 6 worker 生效。
- `progress.md`：追加本轮测试策略校正和验证记录。
- 回滚方式：还原 `backend/tests/test_dlsite_bonus_probe_service.py` 本轮测试名称与断言 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 修正翻译版作品特典探测日期来源
### What was done
- 修正社团补全选中作品查特典时的日期来源，优先使用原作发售日，避免繁中/英/韩等翻译版卡片用翻译版发售日触发“已查日期”拦截。
- 同步修正后端 work-codes 返回的 `release_dates_by_rjcode`，让前端刷新后仍按原作日期提交特典探测。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py`：通过。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `backend/app/core/circle_completion_service.py`：`release_dates_by_rjcode` 改为优先读取 `original_release_date`。
- `frontend/src/views/CircleCompletion.vue`：选中作品特典探测日期改为优先读取 `original_release_date`。
- `progress.md`：追加本轮修复和验证记录。
- 回滚方式：还原上述两个代码文件本轮 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 完善选中作品特典探测重跑逻辑
### What was done
- 选中具体作品发起特典探测时，不再被日期级已完成状态提前拦截，允许对指定原作重跑同日探测。
- 复用已有命中索引时不再提前结束扫描，而是把缓存命中特典合并进本轮命中结果后继续探测未完成范围。
- 修正同一轮多个特典映射到同一原作时，原作探测状态在同一事务内重复插入导致唯一键冲突的问题。
- 前端选中作品时不再因为已确认无特典或已查日期直接跳过提交，而是保留提示计数并继续提交该日期。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\circle_completion_service.py app\core\dlsite_bonus_probe_service.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests/test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_uses_date_range_for_far_bonus tests/test_dlsite_bonus_probe_service.py::test_probe_date_reused_hit_index_still_continues_unfinished_scan tests/test_dlsite_bonus_probe_service.py::test_probe_date_counts_cached_hidden_bonus_candidate -q`：通过，3 passed。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。

### Notes
- `backend/app/api/routes.py`：带 `selected_rjcodes_by_date` 的特典探测请求跳过日期级完成复用拦截。
- `backend/app/core/dlsite_bonus_probe_service.py`：缓存命中特典合并到本轮扫描结果，并修复原作状态同事务重复 upsert。
- `frontend/src/views/CircleCompletion.vue`：选中作品已查/无特典时继续提交探测日期，只保留提示计数。
- `progress.md`：追加本轮修复和验证记录。
- 回滚方式：还原上述三个代码文件本轮 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 更新 v1.6.73 Docker 导入版本并验证特典探测
### What was done
- Docker Compose 导入示例和部署文档中的 GHCR 镜像版本更新到 `1.6.73`，与本次即将发布的 semver tag 对齐。
- 调整特典探测缓存候选统计断言，避免日期范围扫描扩大后把全局缓存候选数量误判为业务失败。

### Testing
- `backend/` 下执行 `venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py`：通过，37 passed。

### Notes
- `docker-compose.yml`：默认导入镜像更新为 `ghcr.io/elena3939/kikoerumanager:1.6.73`。
- `DOCKER_DEPLOY.md`：Compose 和 `docker run` 示例镜像版本更新为 `1.6.73`。
- `backend/tests/test_dlsite_bonus_probe_service.py`：缓存候选统计断言改为确认至少命中缓存路径。
- `progress.md`：追加本轮发布配置和验证记录。
- 回滚方式：还原上述三个文件本轮 hunk，并删除本段进度记录；如 tag 已推送，则需删除远程 `v1.6.73` 后重新发布。
## 2026-07-08 - Task: 补齐数据库迁移兜底路径
### What was done
- Docker 单镜像启动流程新增 `alembic upgrade head`，避免迁移文件未执行导致线上结构长期停留在旧版本。
- 启动期兼容迁移新增特典探测缓存字段类型兜底，发现 `dlsite_bonus_probe_cache.price` / `wishlist_count` 不是 `BIGINT` 时自动升级。
- 同步补充通知收件箱 `business_key` 的 TEXT 兜底和数据库迁移执行说明，明确 Alembic 与历史库兼容迁移要同时维护。

### Testing
- `\.venv\Scripts\python.exe -m py_compile .\backend\app\models\database.py`：通过。
- 使用项目 `.venv` 执行独立兼容迁移回归脚本：通过，确认 int4 会生成 `ALTER COLUMN ... TYPE BIGINT`，已有 int8 不会重复执行。
- `$env:PYTHONPATH='backend'; .\backend\venv\Scripts\python.exe -m alembic heads`：通过，当前 head 为 `20260707_0001_bonus_probe_resilience`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。
- `backend` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_database_compat_migrations.py -q --basetemp .pytest-codex-db-migrations`：未进入用例执行，本机 PostgreSQL 测试库 `kikoerumanager_test` 连接超时，改用不依赖测试库的独立回归脚本验证本轮逻辑。

### Notes
- `docker/entrypoint.sh`：启动应用前执行 Alembic 迁移。
- `backend/app/models/database.py`：兼容迁移增加特典探测缓存 BIGINT 和通知 `business_key` TEXT 兜底。
- `backend/tests/test_database_compat_migrations.py`：新增特典探测缓存兼容迁移测试。
- `docs/database-migrations.md`：记录 Docker 启动迁移和历史库兼容迁移规则。
- `progress.md`：追加本轮迁移兜底记录。
- 回滚方式：还原上述文件本轮 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 修复社团补全切换与翻页性能
### What was done
- 后端社团补全新增 state / summary / page / work-codes / recent 分层缓存，L1 使用进程内 TTLCache，L2 使用项目 Redis，并用版本号和 build lock 防止跨请求重复冷构建。
- 写路径统一失效社团补全读模型：单社团递增 Redis version，全量未知范围递增全局 epoch，最近社团目录单独递增 recent version。
- 前端切社团请求收敛为默认只打 `/works`，复用 `/works` 返回的 summary 统计，不再冷启动并发打 `/summary` + `/works`。
- 前端翻页保留旧页内容并显示轻量更新状态，保留卡片入场、hover、active 动效，同时减少 server paging 下虚拟列表重复 measure。
- 修复特典分组中同 canonical 原作/特典的父子挂接，让缓存路径不破坏既有特典展示语义。
- 补充社团补全缓存说明文档，记录 Redis 降级、失效和浏览器验收入口。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\circle_completion_service.py tests\test_circle_completion_paged_view.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py tests\test_circle_completion_bonus_grouping.py -q --basetemp .pytest-codex-circle-cache-final`：通过，17 passed。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- 浏览器打开 `http://localhost:5556/circle-completion` 实测点击社团和翻页：切换 `RG42609` 约 918ms、`RG19615` 约 457ms；翻页 `1 -> 2 -> 3 -> 2` 分别约 444ms、518ms、450ms，过程中卡片保持 10 个，无空白重建，加载状态结束后无残留。
- 本地 API 实测：`/recent?limit=24` 260.6ms -> 86.1ms；`RG42609` works p1 39.8ms -> 11.3ms、p2 25.2ms -> 9.3ms；`RG19615` works p1 39.0ms -> 9.5ms、p2 24.3ms -> 10.1ms；`RG64225` 复测 warm 稳定 8.6-9.9ms。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `backend/app/core/circle_completion_service.py`：新增社团补全 Redis/L1 缓存、singleflight/build lock、版本失效、recent 短缓存，并保持特典分组语义。
- `backend/tests/test_circle_completion_paged_view.py`：新增缓存复用、Redis L2、版本失效和 Redis 不可用降级测试。
- `frontend/src/views/CircleCompletion.vue`：切社团请求收敛、分页缓存、保留旧页的轻量 loading 状态。
- `frontend/src/components/circle/CircleWorksViewport.vue`：server paging 翻页时减少虚拟列表 measure 风暴。
- `docs/circle-completion-performance-cache.md`：新增社团补全缓存与验证说明。
- `progress.md`：追加本轮性能修复记录。
- 回滚方式：还原上述五个代码/文档文件本轮 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 优化社团补全卡片封面加载和暗色视图切换样式
### What was done
- 社团补全作品接口返回封面时优先使用本地 cover API 路径，即使本地文件尚未缓存，也让首屏图片请求先走本机 `/api/circle-completion/cover/*`。
- cover API 从“只读本地文件”升级为“本地命中直接返回，缺失时按需从 DLsite 下载到 `data/img/` 后返回”，避免当前页继续直接等待 DLsite 公网图片。
- 修正 DLsite 图片 URL 里目录 bucket RJ 与真实图片 RJ 混用的问题，缓存文件名取图片文件名里的真实 RJ，避免翻译版 / 关联版封面 404。
- 前端 active 卡片图片从低优先级 lazy 改为 eager/auto，并把视口图片激活队列从 6 提到 8；虚拟列表外图片仍不会一次性挂载。
- 收掉社团补全右上角卡片/列表切换控件在暗色态下的浅色 active 胶囊，不影响 hover/active 动效。
- 社团补全缓存 schema 升到 v4，避免继续读到旧 Redis state/page 里的远程封面 URL 或错误本地文件名。

### Testing
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\circle_image_cache_service.py app\core\circle_completion_service.py app\api\routes.py tests\test_circle_completion_paged_view.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py tests\test_circle_completion_bonus_grouping.py -q --basetemp .pytest-codex-circle-cover-cache`：通过，19 passed。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。
- 通过 `start-all.bat` 重启本地服务后，真实接口 `RG19615 /works` 返回 `/api/circle-completion/cover/RJ01201316_sam.jpg` 这类本地 cover API，不再返回 DLsite CDN。
- 本地 cover API 实测：`RJ01201316_sam.jpg` 首次按需下载 1060.2ms，二次本地命中 8.5ms；截图里的 `RJ244747_sam.jpg` 首次 634.5ms，二次 8.1ms。
- Playwright 打开 `http://localhost:5556/circle-completion` 实测当前视口 10 张卡片、10 张图片全部加载完成，cover 资源耗时约 26-95ms；暗色态 view toggle active 背景 computed 为 `rgba(255, 255, 255, 0.075)`，不再是浅色白胶囊。

### Notes
- `backend/app/core/circle_image_cache_service.py`：新增真实图片 RJ 提取、按需下载候选 URL、缺图单文件锁和允许缺失时返回本地 API URL。
- `backend/app/api/routes.py`：cover 路由缺文件时触发按需下载后返回本地文件。
- `backend/app/core/circle_completion_service.py`：社团补全返回本地 cover API，缓存命名取图片真实 RJ，并提升读模型 schema 版本。
- `backend/tests/test_circle_completion_paged_view.py`：补充封面缓存 URL 和图片 RJ 提取测试。
- `frontend/src/components/circle/WorkCard.vue`：active 卡片封面使用 eager/auto 优先级。
- `frontend/src/components/circle/CircleWorksViewport.vue`：图片激活队列上限从 6 调整为 8。
- `frontend/src/views/CircleCompletion.vue`：修复暗色态 view toggle active 背景。
- `docs/circle-completion-performance-cache.md`：补充封面缓存按需下载说明。
- `progress.md`：追加本轮修复和验证记录。
- 回滚方式：还原上述文件本轮 hunk，并删除本段进度记录；如需清理验证产生的封面缓存，可删除 `data/img/RJ01201316_sam.jpg`、`data/img/RJ244747_sam.jpg` 等本轮按需下载文件。
## 2026-07-08 - Task: 修正社团补全视图切换控件浅色兜底
### What was done
- 继续排查用户截图里的右上角白色胶囊，确认真实运行态可能没有把 `dark` / `kikoerumanager-dark` class 挂在 `html` 或 `body` 上，导致之前只依赖暗色选择器的覆盖不稳定。
- 将社团补全卡片 / 列表切换控件的基础样式改为深色中性背景，active / hover / inactive 图标也改为深色背景上可读的浅色文本，避免任何主题 class 漏挂时出现白色胶囊。
- 保留原有按钮 hover 上浮、active 缩放和图标动效，没有降低前端动画效果。

### Testing
- Playwright 打开 `http://localhost:5556/circle-completion`，强制清空 `html` / `body` / `#app` 主题 class 后读取 computed style：`view-toggle-group` 背景为 `rgba(20, 22, 26, 0.72)`，active 背景为 `rgba(255, 255, 255, 0.075)`，不再出现浅色胶囊。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：将 `view-toggle-group` 和 `view-toggle-btn` 的基础样式改为深色中性兜底，避免主题 class 漏挂时显示浅色背景。
- `progress.md`：追加本轮补充修复和验证记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 本轮 view-toggle 基础样式 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 修正社团补全视图切换 active 白色高光
### What was done
- 根据用户截图和真实页面复测，确认右上角白色块仍来自卡片 / 列表视图切换控件的 active 高光；cache miss 或翻页加载时页面视觉暗下去后，这个白色半透明高光会更显眼。
- 将视图切换按钮 hover / active 从白色半透明高光改为暗蓝色渐变与蓝色边框，保留 hover 上浮、active 缩放和图标动效，不降低动画效果。
- 继续保留页面级 cache miss loading 的顶部细进度线方案，避免恢复右上角浮动 loading 胶囊。

### Testing
- 应用内浏览器打开 `http://localhost:5556/circle-completion`，点击分页后截取右上角区域复验：active toggle 从 `rgba(255, 255, 255, 0.075)` 改为 `linear-gradient(rgba(59, 130, 246, 0.18), rgba(30, 64, 175, 0.12))`，边框为 `rgba(96, 165, 250, 0.3)`，截图区域不再出现白色胶囊。
- 应用内浏览器复验当前页封面：可见 `img.work-cover` 10 张全部 `complete=true`，图片来源均为本地 `/api/circle-completion/cover/*.jpg`。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning；`precompress-assets` 输出 `created 134, skipped 51`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：将 view-toggle hover / active 高光从白色半透明改为暗蓝色高光，避免暗色页面加载时右上角出现白块。
- `progress.md`：追加本轮补充修复和验证记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 本轮 view-toggle active / hover 样式 hunk，并删除本段进度记录。
## 2026-07-08 - Task: 修正社团补全卡片模式选中态蓝色高光
### What was done
- 根据用户截图，确认卡片 / 列表视图切换控件的卡片模式 active 态被上一轮改成蓝色高光，和当前暗色界面不协调。
- 将该 active / hover 态从蓝色改回中性暗色高光：保留选中识别、hover 上浮、active 缩放和图标动效，但不再显示蓝色方块。

### Testing
- 应用内浏览器打开 `http://localhost:5556/circle-completion` 复验 computed style：`.view-toggle-btn.active` 背景为 `linear-gradient(rgba(244, 244, 245, 0.06), rgba(244, 244, 245, 0.03))`，边框为 `rgba(244, 244, 245, 0.16)`，不再是蓝色。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning；`precompress-assets` 输出 `created 134, skipped 51`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：将 view-toggle active / hover 从蓝色高光改回中性暗色高光。
- `progress.md`：追加本轮补充修复和验证记录。
- 回滚方式：还原 `frontend/src/views/CircleCompletion.vue` 本轮 view-toggle active / hover 中性高光 hunk，并删除本段进度记录。

## 2026-07-08 - Task: 压缩社团补全详情顶部布局
### What was done
- 压缩社团补全详情页顶部区域，把已满足页的统计条和筛选条收成可同排的紧凑控制区，减少卡片列表上方占高。
- 移除已满足面板模板上的 Tailwind 大间距，改用页面内受控的 `owned-panel` / `owned-filter-row` / `owned-filter-actions` 布局。
- 收紧社团详情 toolbar、tab header、筛选按钮、搜索框、作品容器 padding 和 gap，让作品卡片 / 空状态区域更早进入可视区域。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning；`precompress-assets` 输出 `created 134, skipped 51`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。
- Playwright 打开 `http://localhost:5556/circle-completion`，切到用户截图对应的“已满足”tab 并截图复验：统计和筛选已同排显示，没有遮挡或换行错位。
- Playwright DOM 实测当前 2048x1110 视口：`toolbar-card` 高度 80px，tab header 33px，`owned-panel` 42px，`works-card` 可用高度 942px。

### Notes
- `frontend/src/views/CircleCompletion.vue`：压缩社团详情 toolbar / tabs / works-card，并将已满足统计和筛选区改为紧凑同排布局。
- `progress.md`：追加本轮布局优化和验证记录。
- 回滚方式：若确认当前同文件未提交改动都不需要保留，可执行 `git restore -- frontend/src/views/CircleCompletion.vue progress.md`；若要保留同文件既有性能 / 缓存改动，只反向应用本轮涉及 `.toolbar-card`、`.circle-tabs`、`.works-card`、`.owned-panel`、`.owned-filter-*` 的 hunk，并删除本段进度记录。

## 2026-07-08 - Task: 合并社团补全已满足筛选与工具栏布局
### What was done
- 将“已满足”页左侧统计条直接改成筛选 tab：总收录、简中、繁中、原作、字幕、特典都直接点击筛选，删除右侧重复筛选条。
- 删除“已满足”页内部第二个发售时间排序按钮，只保留 tabs 顶部工具行里的统一排序入口。
- 将“已满足”搜索框移动到顶部工具行，与排序、状态筛选、视图切换同排显示。
- 缩短统计筛选条为内容宽度，避免横向铺满整行；同时修正顶部搜索框高度，避免上沿被工具行裁切。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning；`precompress-assets` 输出 `created 134, skipped 51`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。
- Playwright 打开 `http://localhost:5556/circle-completion`，切到“已满足”tab 复验：顶部搜索框位置为 top 163 / bottom 193，高度 30px，位于工具行 top 161 / bottom 195 内，不再被裁切。
- Playwright 实测“已满足”tab 内部重复排序按钮数量为 0，左侧统计筛选条宽度 534px，不再横向铺满。

### Notes
- `frontend/src/views/CircleCompletion.vue`：合并已满足筛选和统计条，移动搜索框到顶部工具行，删除重复排序，缩短筛选统计条并修复搜索框裁切。
- `progress.md`：追加本轮布局收口和验证记录。
- 回滚方式：若确认当前同文件未提交改动都不需要保留，可执行 `git restore -- frontend/src/views/CircleCompletion.vue progress.md`；若要保留同文件既有性能 / 缓存改动，只反向应用本轮涉及 `.owned-stat-item`、`.owned-stats-strip`、`.owned-search-wrap--top`、`.circle-tabs-wrapper.has-owned-search` 的 hunk，并删除本段进度记录。

## 2026-07-08 - Task: 修复选中 RJ01624471 特典探测无明确日期
### What was done
- 修复社团补全 work-codes 给特典探测返回发售日的逻辑：当本地缓存里只有 `2026年05月下旬` 这类模糊日期时，先按 canonical 原作 RJ 调 DLsite product/info 补精确 `regist_date`。
- 日期优先级改为 canonical 原作日期优先，避免 RJ01624471 被繁中 / 简中显示版本的发售日带偏到翻译版日期。
- 社团补全缓存 schema 升到 v6，避免继续读到旧 Redis / L1 work-codes 里的模糊日期。

### Testing
- `\.venv\Scripts\python.exe -m py_compile .\backend\app\core\circle_completion_service.py .\backend\tests\test_circle_completion_paged_view.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --basetemp .pytest-codex-bonus-date`：通过，12 passed。
- 使用当前代码直连本地数据执行 `list_circle_completion_work_codes('RG68316')`：确认 `RJ01624471` 的特典探测日期从模糊日期补为 `2026-05-31`，并保留请求链 `RJ01641421 / RJ01624471 / RJ01641422`。
- 启动本地特典探测任务 `3737493f-8a26-44fd-9b34-0bc1ebe9b79d` 按 `RJ01624471 / 2026-05-31` 跑完：检查 2983 个候选、15 次 DLsite 请求，命中 0、写入 0；因日期页 RJ 范围超出预算，结果为 incomplete，没有写成“确认无特典”结论。

### Notes
- `backend/app/core/circle_completion_service.py`：新增完整日期判断和 canonical 原作 product/info 精确发售日补查，并提升社团补全缓存 schema。
- `backend/tests/test_circle_completion_paged_view.py`：补充模糊日期通过 DLsite product/info 补成完整日期的回归断言。
- `progress.md`：追加本轮 RJ01624471 特典探测日期修复记录。
- 回滚方式：还原上述两个代码文件本轮 hunk，并删除本段进度记录；若线上已产生 v6 社团补全缓存，可等待 TTL 过期或清理对应 Redis cache key。
## 2026-07-08 - Task: 修复社团补全顶部工具按钮裁切
### What was done
- 根据用户截图，修复社团补全顶部工具行里“发售时间”和“状态筛选”按钮在 hover / scale 动效下被上沿裁切的问题。
- 将顶部绝对工具行从贴顶改为保留 3px 安全边界，并保持 30px 紧凑高度，不重新增高顶部区域。
- 给排序按钮和状态筛选按钮补齐 line-height、box-sizing、flex-shrink 与 nowrap 约束，避免文本和按钮自身在同排布局里被压缩。

### Testing
- Playwright 打开 `http://localhost:5556/circle-completion`，切到“已满足”tab 后实测 2048x1110 视口：基础态工具按钮 topClear 为 3px，未越界。
- Playwright hover “发售时间”：按钮 transform 为 `matrix(1.02, 0, 0, 1.02, 0, -2)`，topClear 为 0.7px，`clippedTop=false` / `clippedBottom=false`。
- Playwright hover “状态筛选”：按钮 transform 为 `matrix(1.02, 0, 0, 1.02, 0, -2)`，topClear 为 0.7px，`clippedTop=false` / `clippedBottom=false`。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning；`precompress-assets` 输出 `created 134, skipped 51`。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：调整顶部工具行安全边界，并修复排序 / 状态筛选按钮的行高、盒模型和收缩约束。
- `progress.md`：追加本轮顶部工具按钮裁切修复和验证记录。
- 回滚方式：反向应用本轮涉及 `.circle-tabs-wrapper .toolbar-right-actions`、`.release-sort-button`、`.status-filter-trigger`、`.status-filter-trigger__content`、`.status-filter-trigger__placeholder`、`.release-sort-direction` 的 hunk，并删除本段进度记录。

## 2026-07-09 - Task: 修复 DLsite 隐藏特典探测缓存与模糊发售日归属
### What was done
- 将 DLsite 特典探测 normal / deep 批量大小统一调到 500，并保留 6 并发配置。
- 修复 selected RJ 探测不再因日期页 RJ 范围过大直接 incomplete；选中作品必须完整跑完范围，只有全部跑完仍无命中才写 `no_bonus`。
- 修复同发售日隐藏特典缓存复用：同 maker + 同精确发售日已经扫到隐藏特典时，优先从 `DLsiteBonusProbeCache` / hit index 直接归属；缓存已覆盖目标 RJ 时不再拉 DLsite 日期页、不构造候选、不探测 RJ。
- 修复缓存未覆盖目标 RJ 时的续扫起点：从同发售日已知最大隐藏特典 RJ 之后继续扫，避免重复扫已沉淀的早期特典范围。
- 修复 `2026年05月下旬` / `中旬` / `上旬` 这类模糊日期导致特典无法归属的问题：社团补全 work-codes 会用 DLsite product/info 补精确 `YYYY-MM-DD` 并写回 `WorkMetadata.release_date`；特典探测入口自身也会把 selected RJ 和日期页公开 RJ 的精确发售日写回 PostgreSQL，并清理社团补全 metadata / view 缓存。
- 真实验证 `RG68316 / RJ01624471 / 2026-05-31`：命中隐藏特典 `RJ01637297`，结果为 `parse_status=cached_hidden_bonus`、`selected_cache_covered=true`、`probe_count=0`、`raw_probe_count=0`、`request_count=0`，并写回原作 `release_date=2026-05-31`、`state_status=has_bonus`。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend/app/core/dlsite_bonus_probe_service.py backend/app/core/circle_completion_service.py backend/app/config/settings.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py tests\test_circle_completion_paged_view.py::test_paged_missing_works_and_work_codes -q --basetemp .pytest-codex-bonus-date-cache`：通过，39 passed。
- 使用当前代码直连本地 PostgreSQL 执行 `probe_date(circle_id='RG68316', maker_id='RG68316', release_date='2026-05-31', target_rjcodes=['RJ01624471'], batch_size=500, concurrency=6)`：确认直接命中缓存特典 `RJ01637297`，没有网络探测请求，日期行状态为 completed。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：放开 selected scope 日期页范围上限、复用同日隐藏特典缓存、缓存覆盖目标时早返回、未覆盖时从已知特典后续扫、收窄 selected RJ 状态写回，并新增精确发售日持久化和缓存失效。
- `backend/app/core/circle_completion_service.py`：work-codes 遇到模糊日期时通过 DLsite product/info 补精确发售日并写回 metadata / L1 缓存。
- `backend/app/config/settings.py`、`backend/config/config.yaml`、`data/config/config.yaml`：将 DLsite 特典探测 normal / deep batch size 改为 500。
- `backend/tests/test_dlsite_bonus_probe_service.py`：覆盖 selected scope 超范围完整扫描、缓存覆盖目标不再拉日期页、模糊日期也会写回精确日期、缓存特典命中后直接完成。
- `backend/tests/test_circle_completion_paged_view.py`：覆盖社团补全 work-codes 将模糊发售日补成精确日期并写回 DB / metadata cache。
- `progress.md`：追加本轮 DLsite 隐藏特典探测修复和验证记录。
- 回滚方式：反向应用上述文件本轮 DLsite bonus probe / precise release date / batch size 相关 hunk，并删除本段进度记录；若运行库已写入 `RJ01624471` / `RJ01637297` 的特典归属，可按需删除对应 `dlsite_bonus_probe_*` 行并还原 `work_metadata.release_date`。

## 2026-07-09 - Task: Redis 完整验收与推送前审查
### What was done
- 完成 Redis 运行态、社团补全 Redis/L1 缓存、DLsite 特典 dirty buffer、任务中心实时/物化链路和数据库迁移兜底的推送前验收。
- 实测本机 Redis 使用项目配置 URL 可用，裸 `redis://localhost:6379/0` 因认证失败不可用，验收改用项目 Redis 配置，避免误判。
- 修正 `test_routes_maintenance_config.py` 中 DLsite 特典探测默认批量大小断言，和当前 `BonusProbeConfig` / `backend/config/config.yaml` 的 500/500 默认值保持一致。
- 审查当前 diff 未发现 Redis 不可用降级、Redis URL 脱敏回写、缓存版本失效、Docker 启动迁移顺序方面的新问题。

### Testing
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-redis.ps1`：通过，项目配置 Redis 已 ready。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m py_compile app\core\redis_service.py app\core\circle_completion_service.py app\core\dlsite_bonus_probe_service.py app\core\circle_image_cache_service.py app\api\routes.py app\config\settings.py app\models\database.py`：通过。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_redis_config.py tests\test_routes_maintenance_config.py tests\test_database_compat_migrations.py tests\test_dlsite_bonus_probe_service.py tests\test_circle_completion_paged_view.py tests\test_circle_completion_bonus_grouping.py -q --basetemp .pytest-codex-redis-acceptance`：通过，100 passed。
- `backend/` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_task_center_service.py -q --basetemp .pytest-codex-redis-task-center`：通过，19 passed。
- `backend/` 下执行 Redis JSON set/get/delete 冒烟：通过，`redis_acceptance_ok`。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- `git diff --check`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `backend/tests/test_routes_maintenance_config.py`：将 `BonusProbeConfig` 默认 normal/deep batch size 断言更新为 500/500。
- `progress.md`：追加本轮完整 Redis 验收、审查和测试记录。
- 回滚方式：反向应用 `backend/tests/test_routes_maintenance_config.py` 的默认批量断言 hunk，并删除本段进度记录；验收过程中写入的 Redis 临时 key 已在脚本中删除。

## 2026-07-09 - Task: 根据项目真实变更更新 AGENTS 接手说明
### What was done
- 基于最近已合入的 Redis 运行态、社团补全读模型缓存、DLsite 特典探测和社团补全已满足工具栏变更，更新仓库接手说明。
- 补充 Redis 依赖、Docker 内置 Redis、`/app/data/redis` 持久化、Redis URL 脱敏回填和高压任务不可静默降级到 PostgreSQL 的规则。
- 补充社团补全 L1 / Redis / PostgreSQL 缓存层、封面缓存、分页交互、已满足搜索定位和 DLsite 特典探测完成口径 / 异常写结论红线。
- 补充任务中心 Redis Stream / runtime overlay、特典探测任务字段、操作历史 `bonus_probe` / `new_release_bonus_probe` 语义，以及对应验证和排查入口。

### Testing
- `git diff --check -- AGENTS.md`：通过；仅有 Windows autocrlf 的 LF/CRLF 提示。
- `git diff -- AGENTS.md`：已复核改动均来自当前代码、文档和最近提交可确认的真实变更。

### Notes
- `AGENTS.md`：更新 Redis、社团补全缓存、DLsite 特典探测、任务中心 / 操作历史语义、最低验证和常用排查路径。
- `progress.md`：追加本轮 AGENTS 接手说明更新记录。
- 回滚方式：反向应用本轮 `AGENTS.md` 新增条目和本段 `progress.md` 记录，或执行 `git restore -- AGENTS.md progress.md` 回到本轮前状态。

## 2026-07-09 - Task: 聚合同名拆分特典展示
### What was done
- 社团补全作品卡改为在展示层聚合同一父作品下的同名拆分特典，去掉标题末尾 `_01` / `＿０１` 这类编号后作为聚合 key。
- `【早期限定415大特典】_01`、`【早期限定415大特典】_06`、`【早期限定415大特典】_09` 现在展示为一个 `【早期限定415大特典】`，不同基础标题仍分别保留。
- 聚合后的特典保留真实成员 RJ 列表，选中、闪烁定位、已收录、可下载、入库和预览状态按成员合并判断；实际入库 / 预览仍落到可执行的真实 RJ。
- 补充 DLsite 特典探测文档中的展示聚合规则，明确后端不合并写库数据。

### Testing
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- `frontend/` 下执行 Node 标题归一烟测：`【早期限定415大特典】_01`、`【早期限定415大特典】_06` 均归一为 `【早期限定415大特典】`，无编号的 `【早期限定118大特典】` 保持不变。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue docs/dlsite-bonus-probe.md`：通过；仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增特典标题归一、同名拆分聚合、成员 RJ 合并状态和动作代表选择。
- `docs/dlsite-bonus-probe.md`：记录拆分特典只做展示层聚合，后端真实 RJ 和父子关联保持独立。
- `progress.md`：追加本轮特典展示聚合记录。
- 回滚方式：反向应用 `CircleWorksViewport.vue` 的特典聚合 hunk、删除 `docs/dlsite-bonus-probe.md` 的展示规则段落，并删除本段进度记录。

## 2026-07-09 - Task: 降低特典补全与 ASMR.one 故障时的连接压力
### What was done
- 定位 504 的主要压力来源：特典补全期间 `dlsite_bonus_probe_cache` dirty buffer 回写 PostgreSQL 因 `integer out of range` 失败，反复重放同一批 500 行 upsert 并打印巨型 SQL；同一时间 ASMR.one API 大量 522 / connection reset 重试，叠加占用外部 HTTP、DB 和日志 I/O。
- 将 DLsite 特典补全默认并发降压，日期 worker 最多 3 个，日期内 `product/info/ajax` 请求另行限制到最多 2，避免配置并发被两层相乘。
- 将特典缓存回写批次限制到 100，并对 `price` / `wishlist_count` 按 PostgreSQL integer 上限裁剪；dirty buffer 回写失败会 ACK 当前批次，避免毒消息无限重放。
- 修复特典任务运行态计数：后端先写 `bonus_probe_meta` 再发任务中心事件，实时事件携带轻量计数字段，前端进度卡合并运行态后能显示已查 RJ / 命中特典 / 请求等数值。
- 为 ASMR.one `workInfo` / `tracks` 增加短熔断：连续失败后 5 分钟内直接跳过后续 ASMR.one 请求，不再继续打满连接。
- 同步后端模板配置、本地运行配置、设置页默认值和相关文档。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\core\dlsite_bonus_probe_service.py backend\app\core\task_engine.py backend\app\core\task_center_event_service.py backend\app\core\asmr_download_service.py backend\app\config\settings.py`：通过。
- `frontend/` 下执行 `npm run build`：通过，预压缩 `created 134, skipped 51`；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- 使用项目 Python 执行不依赖 pytest / 测试库的逻辑烟测：ASMR.one 连续 522 后打开熔断，后续 RJ 不再发 HTTP；特典 runtime limit 将 concurrency 截断为 3、`product_info_concurrency=2`、`cache_write_batch_size=100`。
- `git diff --check -- backend/app/config/settings.py backend/app/core/asmr_download_service.py backend/app/core/dlsite_bonus_probe_service.py backend/app/core/task_center_event_service.py backend/app/core/task_engine.py backend/config/config.yaml backend/tests/test_asmr_download_service.py backend/tests/test_dlsite_bonus_probe_service.py docs/dlsite-bonus-probe.md docs/library-folder-completion-implementation.md frontend/src/components/settings/ServicesSettingsPanel.vue frontend/src/views/CircleCompletion.vue progress.md`：通过；仅有 Windows autocrlf 的 LF/CRLF 提示。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_dlsite_bonus_probe_service.py backend\tests\test_asmr_download_service.py -q`：未进入用例执行；`backend/tests/conftest.py` 初始化 PostgreSQL 测试库 `kikoerumanager_test` 时连接超时，后续收窄 pytest 也卡在同一初始化问题，已清理残留 pytest 进程。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：限制特典补全两层并发、缓存数值按旧 integer 表安全裁剪、dirty buffer 回写失败 ACK 并缩小写回批次。
- `backend/app/config/settings.py`、`backend/config/config.yaml`、`data/config/config.yaml`：将特典补全默认并发和缓存写回批次降压。
- `backend/app/core/task_engine.py`、`backend/app/core/task_center_event_service.py`：修正特典运行态写入顺序，并在任务中心实时事件中带出轻量计数。
- `backend/app/core/asmr_download_service.py`：新增 ASMR.one API 连续失败短熔断，保护 `fetch_work_info` / `fetch_track_list` 入口。
- `frontend/src/views/CircleCompletion.vue`、`frontend/src/components/settings/ServicesSettingsPanel.vue`：合并特典运行态计数并降低设置页默认并发上限。
- `backend/tests/test_dlsite_bonus_probe_service.py`、`backend/tests/test_asmr_download_service.py`：补充 dirty buffer 失败 ACK、并发截断和 ASMR 熔断回归测试。
- `docs/dlsite-bonus-probe.md`、`docs/library-folder-completion-implementation.md`：记录特典限流 / dirty buffer 策略和 ASMR.one 熔断行为。
- `progress.md`：追加本轮卡顿调查、优化和验证记录。
- 回滚方式：反向应用上述文件中本轮特典并发 / dirty buffer / ASMR 熔断 / 前端计数相关 hunk，并删除本段进度记录；若只需恢复运行态配置，可先将 `backend/config/config.yaml` 与 `data/config/config.yaml` 的 `bonus_probe.*_concurrency` 和 `cache_write_batch_size` 改回旧值。

## 2026-07-09 - Task: 彻查并修复特典缓存 price / wishlist_count 字段反复溢出
### What was done
- 确认日志里的 `integer out of range` 来自运行库字段结构漂移：SQLAlchemy 已按 `::BIGINT` 绑定 `price` / `wishlist_count`，但旧运行库字段曾仍是 PostgreSQL `integer`。
- 修正 DLsite 特典缓存初始 Alembic 迁移，新建库直接创建 `BIGINT` 字段，不再先建 `INTEGER` 再依赖后续补丁迁移。
- 加强 2026-07-07 正式迁移和应用启动兼容迁移：执行 `ALTER TABLE ... TYPE BIGINT` 后复查 `information_schema.columns.udt_name`，未变成 `int8` 直接报错，不允许静默继续写旧结构。
- 修复 `init_db()` 初始化完成标记时机，只有数据库自检、建表、扩展索引和兼容迁移全部成功后才设置 `_init_db_done=True`；迁移失败后同进程内后续启动路径仍可重试，不再被误跳过。
- 撤销特典缓存按旧 `integer` 上限归零的临时策略，`2147483648+` 这类合法 PostgreSQL `BIGINT` 值会正常保留，只拦截负数、布尔值、无法解析值和超过 `BIGINT` 上限的异常值。
- 实际连接服务器 PostgreSQL 外部入口检查当前运行库，`dlsite_bonus_probe_cache.price` 和 `wishlist_count` 当前均为 `int8`。
- 同步数据库迁移说明和 DLsite 特典探测文档，明确该字段必须保持 `BIGINT`，启动兼容迁移必须强校验。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\models\database.py backend\app\core\dlsite_bonus_probe_service.py backend\alembic\versions\20260702_0001_dlsite_bonus_probe.py backend\alembic\versions\20260707_0001_bonus_probe_resilience.py`：通过。
- 使用项目 Python 执行迁移烟测：模拟旧 `int4` 字段时，兼容迁移会对 `price` / `wishlist_count` 执行 `ALTER COLUMN ... TYPE BIGINT`，并复查类型变成 `int8`。
- 使用项目 Python 执行缓存值烟测：`price=2147483648`、`wishlist_count=2147483649` 会按原值保留，不再按旧 `integer` 上限归零。
- 使用项目 Python 执行初始化失败烟测：兼容迁移抛 `schema drift` 时，`init_db()` 会抛错且 `_init_db_done` 保持 `False`。
- 服务器运行库实查：通过 `100.85.17.10:15432` 连接 PostgreSQL，`information_schema.columns` 返回 `price=int8`、`wishlist_count=int8`。
- `git diff --check -- backend/app/models/database.py backend/alembic/versions/20260702_0001_dlsite_bonus_probe.py backend/alembic/versions/20260707_0001_bonus_probe_resilience.py backend/app/core/dlsite_bonus_probe_service.py backend/tests/test_database_compat_migrations.py backend/tests/test_dlsite_bonus_probe_service.py docs/database-migrations.md docs/dlsite-bonus-probe.md`：通过；仅有 Windows autocrlf 的 LF/CRLF 提示。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_database_compat_migrations.py backend\tests\test_dlsite_bonus_probe_service.py -q`：仍卡在测试初始化阶段无用例输出，已停止残留 pytest 进程；本轮用不依赖测试库的项目 Python 烟测覆盖核心逻辑。

### Notes
- `backend/alembic/versions/20260702_0001_dlsite_bonus_probe.py`：新建 `dlsite_bonus_probe_cache` 时直接使用 `BIGINT` 存储 `price` / `wishlist_count`。
- `backend/alembic/versions/20260707_0001_bonus_probe_resilience.py`：升级旧字段后复查 `udt_name=int8`，失败时阻断迁移。
- `backend/app/models/database.py`：启动兼容迁移升级旧字段后强校验；`init_db()` 迁移成功后才标记完成。
- `backend/app/core/dlsite_bonus_probe_service.py`：特典缓存数值边界改为 PostgreSQL `BIGINT`，不再按旧 `integer` 上限归零。
- `backend/tests/test_database_compat_migrations.py`、`backend/tests/test_dlsite_bonus_probe_service.py`：补充字段升级强校验、初始化失败不误标记完成、合法 bigint 数值保留的回归覆盖。
- `docs/database-migrations.md`、`docs/dlsite-bonus-probe.md`：记录特典缓存数值列必须为 `BIGINT` 以及迁移后类型复查要求。
- `progress.md`：追加本轮字段根因调查、修复和验证记录。
- 回滚方式：反向应用上述文件中本轮 `BIGINT` 字段强校验、`init_db()` 标记时机、数值边界和文档 / 测试 hunk，并删除本段进度记录；运行库若已升级为 `BIGINT` 不建议回退到 `INTEGER`，除非先确认不会再写入超过 32 位整数的缓存值。

## 2026-07-09 - Task: 移除误提交的本地 Docker 导入模板
### What was done
- 移除误提交到仓库的群晖 Docker 容器导入配置。
- 该文件包含具体部署实例路径，属于本机 / 群晖环境配置，不是项目源码或通用发布产物。

### Testing
- `Test-Path docker\synology\elena39-kikoerumanager-postgresql-single.json`：返回 `False`。
- `git diff --check -- progress.md docker/synology/elena39-kikoerumanager-postgresql-single.json`：通过。

### Notes
- `docker/synology/elena39-kikoerumanager-postgresql-single.json`：删除误提交的本地 Docker 导入模板。
- `progress.md`：修正本轮记录，说明移除原因和验证方式。
- 回滚方式：从提交 `9682afcc` 恢复 `docker/synology/elena39-kikoerumanager-postgresql-single.json`，并还原本段进度记录。

## 2026-07-09 - Task: 调查特典补全卡顿与封面缓存重复下载
### What was done
- 实查服务器日志、健康接口和 PostgreSQL 活动，确认本次不是数据库锁、连接池打满或 `price / wishlist_count` 字段问题；卡顿发生在 `circle_completion_bonus_probe` 开始后，DLsite 新作日期页连接失败进入重试，期间大量封面请求也在等待外网下载。
- 保持封面“缺图时下载到本地再读取”的业务语义不变，修复 Docker 环境封面缓存目录：优先使用 `DATA_PATH/img`，默认落到持久化卷 `/app/data/img`，不再由 `/app/config/config.yaml` 错推到 `/app/img`。
- 给 DLsite 新作日期页请求增加特典链路快速失败：该请求不再走 2/4/8 秒重试和 one-shot 兜底，单次 `connect=5s / read=10s` 失败后返回 `http_error`，特典层按既有规则标记该日期 `incomplete`，不写 `no_bonus`。
- 新增事件循环 watchdog：启动后记录主循环延迟；如果主循环心跳停顿，独立守护线程会把所有 Python 线程栈写入日志，便于下次直接定位同步阻塞点。
- 同步社团补全缓存、DLsite 特典探测和性能诊断文档，明确封面缓存持久化目录、日期页快速失败规则和 watchdog 行为。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m py_compile backend\app\api\routes.py backend\app\core\dlsite_service.py backend\app\core\circle_image_cache_service.py`：通过。
- 使用项目 Python 执行封面缓存目录烟测：设置 `DATA_PATH=D:\Tool\ASMR\KikoeruTool_Elena_StartAll\data` 后，`CircleImageCacheService.cache_dir` 返回 `D:\Tool\ASMR\KikoeruTool_Elena_StartAll\data\img`。
- 使用项目 Python 执行 DLsite 日期页快速失败烟测：模拟 `ConnectError` 时，`list_new_work_summaries_by_date('2024-06-04')` 只调用 1 次 `_guarded_get`，参数 `retry=False`，返回 `http_error`。
- `git diff --check -- backend/app/api/routes.py backend/app/core/dlsite_service.py backend/app/core/circle_image_cache_service.py docs/circle-completion-performance-cache.md`：通过，仅有 Windows autocrlf 的 LF/CRLF 提示。

### Notes
- `backend/app/core/circle_image_cache_service.py`：封面缓存目录优先走 `DATA_PATH/img`，确保 Docker 下落到 `/app/data/img` 持久化卷。
- `backend/app/core/dlsite_service.py`：`_guarded_get()` 增加可选快速失败参数，并让新作日期页请求使用短 timeout + `retry=False`。
- `backend/app/api/routes.py`：新增事件循环 watchdog，在卡顿时输出主循环延迟和线程栈。
- `docs/circle-completion-performance-cache.md`：记录 Docker 封面缓存持久化目录规则。
- `docs/dlsite-bonus-probe.md`：记录新作日期页网络失败必须快速 `incomplete`，不能拖住整站或写 `no_bonus`。
- `docs/system-performance-bottleneck-audit-2026-06-09.md`：记录事件循环 watchdog 诊断能力。
- `progress.md`：追加本轮调查、修复和验证记录。
- 回滚方式：反向应用上述文件中本轮 `DATA_PATH/img`、日期页 `retry=False` / 短 timeout、事件循环 watchdog 和文档 hunk，并删除本段进度记录；若只回滚诊断能力，可仅还原 `backend/app/api/routes.py` 中 `_EVENT_LOOP_WATCHDOG_*` 相关 hunk。

## 2026-07-09 - Task: HTTP 高压下控制面不卡死优化
### What was done
- 新增 `runtime_buffer` 运行态配置，明确只缓冲任务进度、事件和日志流批次，不改 HTTP / ASMR / 百度下载并发、aria2 `split` 或连接数配置。
- 扩展 Redis 运行态：任务下载中的 `download_files` / `failed_files` / runtime / progress log 优先进入 Redis；Redis 不可用时降级到进程内 memory fallback，已有下载不被中断。
- 将系统日志读取、日志搜索、日志管理切到专用 `system-log-io` bounded thread pool，避免日志页被默认 executor 中的下载、解析和数据库写入挤占。
- `/api/logs/stream` 增加固定批次保护，超过批次只推最新日志并返回 `dropped_count` / `next_offset`，前端日志页显示“流保护跳过 N”，避免一次 SSE 把大增量塞到页面导致白屏。
- 任务中间态持久化削峰：下载 / 上传中的大文件明细不再每个 progress tick 全量写 PostgreSQL，只保存轻量摘要；完成、失败、取消、等待人工 / 重试状态仍强制完整落库。
- 新增控制面诊断接口：`/api/system/pressure`、`/api/system/runtime-buffer/status`、`/api/logs/stream/status`，用于查看资源预算、runtime buffer、日志线程池、任务队列和数据库连接池压力。
- 新增文档说明控制面隔离、运行态缓冲、日志流保护、诊断接口和“不改下载数据面配置”的边界。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend/app/config/settings.py backend/app/core/redis_service.py backend/app/core/task_engine.py backend/app/api/routes.py`：通过。
- `frontend/` 下执行 `npm run build`：通过，预压缩 `created 134, skipped 51`；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- 使用项目 Python 执行 runtime buffer memory fallback 烟测：强制 `KIKOERUMANAGER_REDIS_ENABLED=0` 后，HTTP 下载任务运行态可写入 / 读取进程内 memory，事件 stream 返回 `memory-*` id。
- `git diff --check -- backend/app/config/settings.py backend/config/config.yaml backend/app/core/redis_service.py backend/app/core/task_engine.py backend/app/api/routes.py frontend/src/views/Logs.vue docs/runtime-buffer-control-plane.md progress.md`：通过；仅有 Windows autocrlf 的 LF/CRLF 提示。
- `powershell -ExecutionPolicy Bypass -File scripts/check-redis.ps1`：未通过；本机 `redis-server` 不在 PATH，且 `redis://:123456@localhost:6379/0` 不可达。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest backend/tests/test_redis_config.py backend/tests/test_routes_maintenance_config.py backend/tests/test_database_compat_migrations.py -q`：90 秒无输出，卡在测试初始化阶段，已停止残留 pytest 进程。

### Notes
- `backend/app/config/settings.py`、`backend/config/config.yaml`：新增 `runtime_buffer` 配置项及默认值。
- `backend/app/core/redis_service.py`：新增 runtime buffer 配置读取、任务运行态 memory fallback、事件 stream memory ring 和状态诊断。
- `backend/app/core/task_engine.py`：中间态任务快照瘦身并按 `progress_flush_interval_seconds` 合并写库，终态 / 等待态保持完整持久化。
- `backend/app/api/routes.py`：日志 I/O 专用线程池、日志流批次保护、runtime overlay 扩展和新增压力诊断接口。
- `frontend/src/views/Logs.vue`：展示日志流保护性跳过数量。
- `docs/runtime-buffer-control-plane.md`：记录控制面运行态缓冲设计、配置、接口和边界。
- `progress.md`：追加本轮优化和验证记录。
- 回滚方式：反向应用上述文件中本轮 `runtime_buffer`、Redis memory fallback、日志线程池 / SSE 批次保护、任务中间态瘦身、前端跳过提示和文档 hunk，并删除本段进度记录；若只需临时关闭运行态缓冲，可先把 `runtime_buffer.enabled` 改为 `false`。

## 2026-07-09 - Task: 拆分 DLsite 特典缓存超大 RJ 查询
### What was done
- 将 `DLsiteBonusProbeCache.rjcode.in_(...)` 统一收口到缓存回表 helper，避免各入口直接构造超大 `IN`。
- 小批量缓存读取按 `cache_lookup_batch_size` 分批查询，默认从 500 调整为 1000，并限制最大 3000。
- PostgreSQL 且 RJ 数量达到 3000 时，改用 session 临时表写入 RJ 列表后 `JOIN dlsite_bonus_probe_cache` 回查，减少 SQLAlchemy 参数绑定、网络传输和 PostgreSQL 解析 / planner 压力。
- 临时表路径失败时自动回退分批 `IN`，避免单次优化失败阻断特典探测。
- 命中索引复用隐藏特典的回表查询也改走同一 helper，不再一次性把 `hit_rjcodes` 全塞进 `IN`。

### Testing
- `.\.venv\Scripts\python.exe -m py_compile backend/app/core/dlsite_bonus_probe_service.py backend/app/config/settings.py`：通过。
- 使用项目 Python 执行 helper 烟测：2500 个 RJ 拆成 `[1000, 1000, 500]` 三批；PostgreSQL fake db 下 3500 个 RJ 走临时表建表、批量插入和 `JOIN tmp_bonus_probe_rjcodes_*` 查询。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest backend/tests/test_dlsite_bonus_probe_service.py::test_cache_rows_by_rjcodes_sync_splits_large_in_batches backend/tests/test_dlsite_bonus_probe_service.py::test_cache_rows_by_rjcodes_sync_uses_temp_table_for_postgresql_large_lookup -q`：90 秒无输出，仍卡在测试初始化阶段，已停止残留 pytest 进程。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：新增缓存 RJ 批量回表 helper、小批量分批 `IN` 和大批量 PostgreSQL 临时表 `JOIN` 路径。
- `backend/app/config/settings.py`、`backend/config/config.yaml`：调整 `bonus_probe.cache_lookup_batch_size` 默认值和上限。
- `backend/tests/test_dlsite_bonus_probe_service.py`：补充大列表分批 `IN` 与 PostgreSQL 临时表路径测试。
- `docs/dlsite-bonus-probe.md`：记录缓存批量读取不能使用超大 `IN`，以及临时表阈值和回退策略。
- `progress.md`：追加本轮优化和验证记录。
- 回滚方式：反向应用上述文件中本轮 `_cache_rows_by_rjcodes_sync`、临时表路径、`cache_lookup_batch_size` 默认值、测试和文档 hunk，并删除本段进度记录。

## 2026-07-09 - Task: 修复社团特典探测 RJ 计数进度
### What was done
- 根据服务器任务日志确认坏点是特典探测开始后长时间只显示“探测某日 RJ 缺口”，没有把当前发售日候选 RJ 总数推给前端，进度卡只能显示 `0`。
- 后端在候选 RJ shard lease 完成后立即上报 `0/总数`，日期内 `current_probe_*` 计数改成 Redis runtime/SSE 运行态更新，不再把每次 RJ 计数写进 PostgreSQL `progress_log`。
- 前端特典进度卡同时读取 `probe_count`、`current_probe_total_count`、`raw_probe_count` 和对应已查字段，并对同一任务做单调合并，避免旧轮询包里的 `0` 覆盖 Redis 实时计数；切换到新任务时重置计数基线，避免串任务。
- 放宽 `dlsite_bonus_probe_dates.mode` 到 `VARCHAR(64)` 并补 Alembic 迁移，修复服务器日志里 `new_release:date-range-v4` 写入 `VARCHAR(20)` 截断导致的新作特典任务失败。
- 同步 DLsite 特典探测文档，明确日期内 RJ 计数属于 Redis 运行态字段，候选总数出来后必须先推 `0/总数`。

### Testing
- `.\venv\Scripts\python.exe -m py_compile app/core/dlsite_bonus_probe_service.py app/core/task_engine.py app/models/database.py alembic/versions/20260702_0001_dlsite_bonus_probe.py alembic/versions/20260709_0001_bonus_probe_mode_width.py`：通过。
- `frontend/` 下执行 `npm run build`：通过；仅有既有 VueUse pure annotation、lottie eval 和 chunk size warning。
- 使用项目 Python 执行直接烟测：缓存 RJ 读取 2500 个拆 `[1000, 1000, 500]`，PostgreSQL fake db 下 3500 个走临时表 `JOIN`；`probe_date()` 在候选集确定后首个进度事件为 `checked_probe_count=0 / probe_count=3`；TaskEngine 收到 `current_probe_*` 后触发 `bonus_probe_meta` 事件且不把 `RJ 缺口：0/3` 写入 `progress_log`。
- `.\venv\Scripts\python.exe -m pytest tests/test_dlsite_bonus_probe_service.py::test_cache_rows_by_rjcodes_sync_splits_large_in_batches tests/test_dlsite_bonus_probe_service.py::test_cache_rows_by_rjcodes_sync_uses_temp_table_for_postgresql_large_lookup tests/test_dlsite_bonus_probe_service.py::test_probe_date_emits_candidate_total_before_probe_requests -q --basetemp .pytest-codex-bonus-progress`：60 秒无输出，卡在测试初始化阶段，已停止残留 pytest 进程。
- `.\venv\Scripts\python.exe -m pytest tests/test_task_engine.py::TestTaskEngine::test_bonus_probe_current_count_progress_uses_metadata_event_not_progress_log -q --basetemp .pytest-codex-task-bonus-progress`：60 秒无输出，卡在测试初始化阶段，已停止残留 pytest 进程。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：候选 shard lease 后立即上报日期内 `0/总数` 进度。
- `backend/app/core/task_engine.py`：特典日期内 RJ 计数走静默 progress/current_step 更新加 `touch_metadata('bonus_probe_meta')`，由 Redis runtime/SSE 承载高频进度。
- `frontend/src/views/CircleCompletion.vue`：进度卡读取 current/raw/summary 多来源计数，合并时同任务单调递增、新任务重置。
- `backend/app/models/database.py`、`backend/alembic/versions/20260702_0001_dlsite_bonus_probe.py`、`backend/alembic/versions/20260709_0001_bonus_probe_mode_width.py`：将 `dlsite_bonus_probe_dates.mode` 放宽到 64 字符并补运行库迁移。
- `backend/tests/test_dlsite_bonus_probe_service.py`、`backend/tests/test_task_engine.py`：补充候选总数先发、缓存大查询和运行态计数不刷 progress_log 的回归测试。
- `docs/dlsite-bonus-probe.md`：记录 RJ 计数运行态语义。
- `progress.md`：追加本轮计数修复、验证和回滚记录。
- 回滚方式：反向应用上述文件中本轮 `emit_probe_progress(0, ...)`、`bonus_probe_meta` 静默运行态更新、前端计数合并、`mode` 字段放宽、测试和文档 hunk，并删除本段进度记录；若运行库已执行 `20260709_0001_bonus_probe_mode_width`，不建议回退到 `VARCHAR(20)`，除非同时停止写入 `new_release:date-range-v4`。

## 2026-07-09 - Task: 修复单选 RJ 特典探测重复命中旧特典
### What was done
- 根据 `RJ01192535` 单选特典探测现场确认：前端会按选中作品传 `selected_rjcodes_by_date={"2024-06-04":["RJ01192535"]}`，问题不在日期选择范围。
- 保留隐藏特典结构判断不强制同日：真实存在“特典登记日早于原作发售日”的样本，不能把 `_hidden_bonus_matches()` 改成同日期硬过滤。
- 修复单选目标的缓存复用短路：不同发售日的历史隐藏特典不再覆盖当前选中原作；同一发售日内按同 maker 公开 RJ 范围放开编号距离，不再被选中 RJ 附近窗口卡死。
- 移除单选探测里“未覆盖目标但已有隐藏特典时，从最大命中特典 RJ 后继续扫”的裁剪逻辑，避免旧命中把真实候选范围截掉，导致每次都重复命中同一批历史特典。
- 修复日期页候选范围污染：日期页只提供同 maker 的公开 RJ 边界，不能拿当天全站 RJ 构造超大范围；分类不做硬过滤，图片等非音声特典仍靠 `product/info/ajax` 结构识别。
- 补充回归测试，覆盖跨日期历史命中 / 旧脏 `bonus` 链不能覆盖当前选中 RJ、同发售日远距离特典仍可覆盖选中 RJ、日期页只取同 maker 边界，以及非 SOU 隐藏特典结构仍可命中。

### Testing
- `.\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- 使用项目 Python 直接烟测：`RJ01091762` 仍符合隐藏特典结构判断，但对 `RJ01192535 / 2024-06-04` 的单选相关性返回 `False`；同发售日远距离命中仍允许覆盖。
- 使用项目 DLsite 客户端调用官方 `product/info/ajax`：`RJ01192535` 返回 `RG68316 / 2024-06-04 / SOU / price=1100 / is_sale=True / is_hidden_bonus_audio=False`；反复命中的 `RJ01091762` 返回 `RG68316 / 2023-08-27 / SOU / price=0 / is_free=True / is_oly=True / wishlist_count=0 / is_hidden_bonus_audio=True`，证明旧命中不属于本发售日。
- 使用项目 Python 直接烟测 `_load_public_worknos_for_date('RG68316','RG68316','2024-06-04')`：`public_worknos` 和 `date_page_worknos` 都只返回 `RJ01192535`，不再混入日期页当天全站 RJ；非 SOU 但满足隐藏特典结构的 payload 可被 `_hidden_bonus_matches()` 接受。
- 服务器日志确认同几次单选任务实际探测的是 `2024-06-04`，不是截图里的更新日 `2025-12-20`。
- 尝试执行 `.\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py -q --basetemp .pytest-codex-bonus-rj01192535`：两分钟无输出，卡在测试初始化阶段，已停止残留 pytest 进程。
- 尝试执行聚焦用例 `test_hidden_bonus_match_allows_bonus_registered_before_original_date`、`test_selected_target_cache_reuse_filters_other_release_date_history_hit`、`test_selected_target_cache_reuse_allows_same_release_date_far_hit`、`test_probe_date_reused_hit_index_stops_selected_scope_when_cache_covers_target`：60 秒无输出，仍卡在测试初始化阶段，已停止残留 pytest 进程。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：单选缓存 / 命中覆盖先校验命中 RJ 自身发售日，日期页候选只取同 maker 公开 RJ，并取消旧命中导致的候选范围裁剪。
- `backend/app/core/dlsite_service.py`：日期页列表新增 `n_worklist_item` 切块并把日期页结果强制归一为请求日期；隐藏特典结构识别不再要求 `work_type=SOU`。
- `backend/tests/test_dlsite_bonus_probe_service.py`：保留跨日期隐藏特典结构判断，新增跨日期历史命中过滤、同发售日远距离命中放行、同 maker 日期页边界和非 SOU 特典结构回归测试。
- `docs/dlsite-bonus-probe.md`：明确选中作品探测必须在同一发售日、同 maker 范围内放开 RJ 编号，同时过滤不同发售日历史命中。
- `progress.md`：追加本轮原因、修复和验证记录。
- 回滚方式：反向应用上述文件中本轮 `_selected_hidden_hit_matches_release_date()`、`_explicit_bonus_original_rjcodes_sync()` / `_filter_hidden_hits_for_target_links_sync()`、单选复用传参、移除 `known_hidden_numbers` 裁剪、文档和对应测试 hunk，并删除本段进度记录。

## 2026-07-10 - Task: 修复空发售日隐藏特典被单选探测漏掉
### What was done
- 按 `RJ01192535 -> RJ01203798` 顺序直接硬扫 `product/info/ajax`，使用 `500 RJ / 请求`、`6` 并发，确认真实早期特典是 `RJ01201745`。
- 复核 `RJ01201745` 官方结构：`maker_id=RG68316`、`price=0`、`is_free=true`、`is_oly=true`、`wishlist_count=0`，但 `regist_date / release_date / sales_date / disp_start_date` 均为空。
- 修复隐藏特典识别：不再要求隐藏特典自身必须带发售日；若特典有明确日期则必须匹配当前探测日期，若日期为空则按当前探测日期和同 maker / RJ 范围归属。
- 修复写库复用：空日期隐藏特典写入命中索引、原作状态和社团作品关联时，使用当前探测原作发售日作为归属日期，避免后续复用查不到。
- 保持历史旧特典过滤：`RJ01091762 / 2023-08-27` 仍不会覆盖 `RJ01192535 / 2024-06-04`。

### Testing
- `RJ01192535 -> RJ01203798` 实扫：`11264` 个 RJ、`23` 个请求、`6` 并发、`0` 请求错误；命中 `RJ01201745` 为空日期隐藏特典。
- `RJ01059487 -> RJ01207484` 全区间复核：`147998` 个 RJ、`296` 个请求、`6` 并发、`0` 请求错误；同 maker 历史隐藏特典 `9` 个均有旧日期，`2024-06-04` 明确日期隐藏特典为 `0`，证明此前漏点是 `RJ01201745` 空日期。
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_service.py app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py::test_hidden_bonus_match_allows_missing_bonus_release_date tests\test_dlsite_bonus_probe_service.py::test_selected_hidden_hit_release_date_filters_history_bonus tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_uses_circle_neighbor_range_when_date_page_has_single_anchor -q --basetemp .pytest-codex-rj01201745-final`：通过，`3 passed`；仅有既有 deprecation warning 和 pytest cache warning。

### Notes
- `backend/app/core/dlsite_service.py`：隐藏特典结构识别不再要求 `release_date` 非空。
- `backend/app/core/dlsite_bonus_probe_service.py`：selected 命中日期判断允许空日期特典归属当前探测日期，并在写入 hit index / 原作状态时使用有效探测日期。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增空日期隐藏特典回归，并把 selected 范围测试改为真实 `RJ01201745` 形态。
- `docs/dlsite-bonus-probe.md`：记录空日期隐藏特典规则。
- `progress.md`：追加本轮实查、修复和验证记录。
- 回滚方式：反向应用上述文件中本轮 `release_date` 非空要求移除、`effective_release_date`、空日期 selected 判断、测试和文档 hunk，并删除本段进度记录。

## 2026-07-10 - Task: DLsite 特典探测样本回归与并发缓存收敛
### What was done
- 按用户给出的真实样本补回归：只输入本体 `RJ01149793` / `RJ01165316`，由单选探测自己构造同 maker / 同发售日 RJ 范围，并分别命中、判定 `RJ01158522` / `RJ01171174` 为隐藏特典结构。
- 修复显式 `bonus` 旧链的误归属风险：若本地已有明确特典指向其它原作，单选当前 RJ 时不能复用、覆盖或扫描后抢写该特典。
- 将特典日期 worker 默认上限调整为 6，`product/info/ajax` 总并发用 `bonus_probe.product_info_total_concurrency=6` 均摊，避免 6 个日期 worker 再各自开 6 个 HTTP 请求。
- 保持 Redis 优先路径：读取先走 Redis overlay，缺失 RJ 才打 DLsite；写入先走 Redis dirty buffer，再后台批量回写 PostgreSQL。
- 同步当前运行态 `data/config/config.yaml` 的非敏感 `bonus_probe` 并发和缓存批量配置，避免本机项目继续用旧的 3 并发覆盖代码默认值。

### Testing
- 使用项目 DLsite 客户端实扫验证：从 `RJ01149793` 往后扫到 `RJ01158522`，`8729` 个候选、`18` 个请求、`6` 并发，命中 `RJ01158522`，结构为同 maker、`price=0`、非销售、免费、`is_oly=true`、`wishlist_count=0`、`is_hidden_bonus_audio=true`。
- 使用项目 DLsite 客户端实扫验证：从 `RJ01165316` 往后扫到 `RJ01171174`，`5858` 个候选、`12` 个请求、`6` 并发，命中 `RJ01171174`，结构同样满足隐藏特典判定。
- `cd backend; $env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py app\config\settings.py tests\test_dlsite_bonus_probe_service.py tests\test_routes_maintenance_config.py`：通过。
- `cd backend; $env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_finds_known_rg68316_bonus_pairs tests\test_dlsite_bonus_probe_service.py::test_selected_target_cache_reuse_ignores_explicit_link_to_other_original tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_scope_does_not_steal_bonus_linked_to_other_original tests\test_dlsite_bonus_probe_service.py::test_load_or_probe_features_uses_redis_overlay_before_http tests\test_dlsite_bonus_probe_service.py::test_probe_circle_dates_uses_configured_date_workers tests\test_dlsite_bonus_probe_service.py::test_probe_circle_dates_caps_product_info_concurrency tests\test_routes_maintenance_config.py::test_redis_and_bonus_probe_defaults_use_parallel_probe_workers -q --basetemp .pytest-codex-bonus-regression4`：通过，`8 passed`；仅有既有 deprecation / pytest cache warning。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：将日期 worker 上限改为 6，新增 product/info 总并发均摊，旧显式 bonus 链不再误覆盖当前选中 RJ，并在最终写库前再次过滤目标归属。
- `backend/app/config/settings.py`、`backend/config/config.yaml`：新增 `bonus_probe.product_info_total_concurrency`，默认 `500 RJ / 请求`、6 并发、缓存读取批量 1000。
- `data/config/config.yaml`：同步当前本机运行态 `bonus_probe` 非敏感并发配置，避免启动中的项目继续读旧 3 并发。
- `backend/tests/test_dlsite_bonus_probe_service.py`：补充用户给出的两个本体 / 特典样本回归、旧链防误归属、Redis overlay 不重复 HTTP、6 worker 与 product/info 总并发均摊测试。
- `backend/tests/test_routes_maintenance_config.py`：同步特典探测默认配置断言。
- `docs/dlsite-bonus-probe.md`：记录 6 worker、product/info 总并发均摊和显式旧链不能误覆盖选中原作。
- `progress.md`：追加本轮回归、验证和回滚记录。
- 回滚方式：反向应用上述文件中本轮 6 worker / `product_info_total_concurrency` / 旧链过滤 / 样本回归 / Redis overlay 测试 / 文档 hunk，并将 `data/config/config.yaml` 的 `bonus_probe` 段恢复到回滚前配置；若只需临时降载，可先把 `data/config/config.yaml` 中 `bonus_probe.max_concurrency` 和 `bonus_probe.product_info_total_concurrency` 改小后重启。

## 2026-07-10 - Task: 修复单选特典缓存覆盖后漏扫后续特典
### What was done
- 确认 `RJ01647392` 单选探测漏掉 `RJ01658547` 的直接原因：本地缓存 / 命中索引里已有 `_01` 特典 `RJ01657203` 后，`selected_cache_covered=True` 会跳过候选 lease 和后续 RJ 扫描，导致 `_02` 永远补不到。
- 修复 selected scope 探测流程：手动选中 RJ 即使已有缓存命中，也继续按发售日边界扫描未缓存候选；缓存命中只表示当前原作已有特典线索，不再表示当前发售日编号段已经完成。
- 删除 selected cache 旧短路死分支，避免后续维护误把缓存命中恢复成直接返回。
- 将选中 RJ 的发售日边界规则收敛为同一发售日全站同位数 RJ 边界，并排除 6 位旧 RJ；归属和特典结构仍只信 `product/info/ajax`。
- 补充回归测试覆盖：`RJ01647392` 能同时找到 `RJ01657203` / `RJ01658547`、已有 `_01` 缓存时仍继续扫 `_02`、复用 hit index 但继续扫描、6 位 RJ 不参与 selected range、缓存候选统计不受本机 Redis overlay 污染。
- 真实执行 `RJ01647392` 单选探测后，已将 `RJ01658547` 写入当前运行库的缓存、命中索引、社团作品和原作关联。

### Testing
- `cd backend; $env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- `cd backend; $env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe -m pytest tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_finds_known_rg68316_bonus_pairs tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_uses_date_range_for_far_bonus tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_runs_full_over_limit_range_before_no_bonus tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_rj_scope_uses_circle_neighbor_range_when_date_page_has_single_anchor tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_release_date_range_finds_rj01647392_bonus tests\test_dlsite_bonus_probe_service.py::test_probe_date_selected_scope_continues_after_cached_bonus_cover tests\test_dlsite_bonus_probe_service.py::test_probe_date_reused_hit_index_keeps_scanning_selected_scope_when_cache_covers_target tests\test_dlsite_bonus_probe_service.py::test_selected_release_date_range_ignores_six_digit_targets tests\test_dlsite_bonus_probe_service.py::test_probe_date_counts_cached_hidden_bonus_candidate tests\test_dlsite_bonus_probe_service.py::test_probe_date_emits_candidate_total_before_probe_requests tests\test_dlsite_bonus_probe_service.py::test_load_or_probe_features_uses_redis_overlay_before_http tests\test_dlsite_bonus_probe_service.py::test_probe_circle_dates_caps_product_info_concurrency -q --basetemp .pytest-codex-bonus-final`：通过，`13 passed`；仅有既有 deprecation warning 和 pytest cache warning。
- 真实运行 `probe_date(circle_id='RG68316', maker_id='RG68316', release_date='2026-06-30', target_rjcodes=['RJ01647392'], batch_size=500, concurrency=6)`：`date_page_range_count=14875`、`raw_probe_count=14760`、`probe_count=4778`、`request_count=10`、`hit_rjcodes=['RJ01657203', 'RJ01658547']`、`budget_reached=False`。
- 真实 DB 复核：`RJ01658547` 已存在于 `dlsite_bonus_probe_cache`，`probe_status=ok`、`maker_id=RG68316`、`release_date=2026-06-30`、`is_hidden_bonus_audio=True`、标题为 `【早期購入限定500大特典】_02`；`dlsite_bonus_probe_hit_index` 已有 `RJ01658547 / RG68316 / 2026-06-30`；`circle_works.RJ01647392.linked_rjcodes` 已包含 `RJ01647392`、`RJ01657203`、`RJ01658547`。

### Notes
- `backend/app/core/dlsite_bonus_probe_service.py`：selected scope 不再因 `selected_cache_covered` 跳过候选 lease / 扫描，并清理旧缓存覆盖短路。
- `backend/tests/test_dlsite_bonus_probe_service.py`：新增和调整 selected scope 发售日范围、缓存覆盖继续扫描、6 位 RJ 排除、缓存候选统计隔离等回归测试。
- `docs/dlsite-bonus-probe.md`：记录单选 RJ 按发售日全站同位数 RJ 边界扫描、缓存覆盖仍继续扫、6 位 RJ 排除和 product/info 最终归属规则。
- `progress.md`：追加本轮原因、修复、真实验证和回滚记录。
- 回滚方式：反向应用上述文件中本轮 `should_probe_candidates`、selected cache 死分支删除、selected 发售日边界测试 / 文档 hunk，并删除本段进度记录；若需要回滚本次真实验证写入的运行库数据，可删除 `RJ01658547` 对应 `dlsite_bonus_probe_cache`、`dlsite_bonus_probe_hit_index`、`circle_works` 行，并从 `RJ01647392.linked_rjcodes` 移除 `RJ01658547`。

## 2026-07-11 - Task: 库存索引 API 重命名一致性修复与运行态验收
### What was done
- 修复单条和批量 API 重命名的幂等重放时机：在旧路径存在性检查和元数据请求前读取已存 operation，并严格校验操作类型、库存和源路径集合，避免成功重命名后的同 key 重试先返回 404 或串用其它请求结果。
- 修复批量本地重命名的模糊异常语义：底层整体抛错后不再用空 effects finalize 和解除 mask，改为保留 prepared scope、标记 `reconcile_required` 并返回 202。
- 修复单条本地重命名在文件系统已启动后的外层异常处理：不再错误调用 `fail_prepared()` 解除 mask，统一转后台核对。
- 修正 Redis wake hint 降级测试：明确 Redis 发布失败不改变已提交 PG operation，且未物化 ledger 不得被清理。
- 使用仓库启动器恢复本地 PostgreSQL / Redis / 前后端，并将本地运行库实际升级到库存索引一致性 migration。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\api\routes.py app\core\library_index\mutation_service.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_library_browser_api.py tests/test_library_index_mutation_service.py -q --basetemp=.pytest-codex-api-rename-live5`：通过，`40 passed`。
- 完整库存套件（browser、mutation、generation、self mutation、remote scanner、circle aggregation）：通过，`86 passed`。
- `cd frontend; npm run test -- --run`：通过，`4` 个测试文件、`11 passed`。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check`：通过；仅有工作树既有 LF/CRLF 提示。
- `start-all.bat`：PostgreSQL 5432、Redis 6379、后端 5555、前端 5556 均恢复监听。
- Alembic 实际升级到 `20260710_0001_library_index_consistency`；运行库 catalog 已确认 operation / ledger / effects / pending masks / generations 表、`filesystem_started_at`、entry generation/materialized seq、status 水位/租约/blocked 字段齐全。
- 运行库同时存在新三列唯一索引 `library_id + generation + relative_path` 和 expand 阶段旧二列唯一索引 `library_id + relative_path`，符合 generation 2 启用前的兼容约束。

### Notes
- `backend/app/api/routes.py`：新增严格 operation 重放校验，提前处理 API rename 幂等请求，并收敛单条/批量模糊异常为 reconciliation pending。
- `backend/tests/test_library_index_mutation_service.py`：修正 Redis wake hint 失败后未物化 ledger 的保留断言。
- `progress.md`：追加本轮修复、测试和运行库迁移核验记录。
- 回滚方式：反向应用 `backend/app/api/routes.py` 中 `_stored_mutation_replay_response`、单条/批量 early replay 和 `reconcile_required` 分支，以及对应测试 hunk；数据库 expand migration 如需回滚，先停写并执行 `backend\venv\Scripts\python.exe -m alembic downgrade 20260709_0001_bonus_probe_mode_width`，不得在存在 generation 2 或未完成 mutation 时直接降级。

## 2026-07-11 - Task: 删除闪回真实浏览器延迟响应验收
### What was done
- 在默认本地库存创建唯一测试目录 `CodexIndexFlashbackE2E20260711`，包含根文件和一层子目录文件；确认 watcher 自动生成 reconcile ledger，并等待 `accepted_seq == materialized_seq` 后进入稳定浏览快照。
- 使用真实库存页面右键删除该测试目录；删除前人为延迟第一次 `/api/library/browser/files` 响应 3 秒，制造“删除前旧响应晚到”的竞态。
- 删除完成后等待旧响应释放，再分别核对页面 DOM、磁盘、强制刷新浏览 API、索引水位和跨库索引搜索；最后整页 reload 再次确认测试目录未恢复。
- 验证了下划线开头目录属于项目既有主动跳过规则，因此测试数据改用普通名称，未修改索引跳过语义。

### Testing
- 新增目录入账：watcher/materializer 达到 `accepted_seq=13`、`materialized_seq=13`，浏览 API 命中测试目录 `1` 条。
- 删除竞态：确认删除后等待延迟旧响应额外 `3.5s`，页面 `rowCount=0`、`bodyHasName=false`，未发生闪回。
- 文件系统与后端：测试路径 `Test-Path=False`；`/api/library/browser/files?library_id=local&force_refresh=true` 命中 `0`；最终 `accepted_seq=19`、`materialized_seq=19`、`catchup_state=idle`。
- 整页刷新：reload 后页面 `rowCount=0`、`bodyHasName=false`。
- `/api/library/index/global-search?keyword=CodexIndexFlashbackE2E20260711`：本地索引结果 `count=0`；三个远程库现场 fallback 超时，但未影响本地索引结论。

### Notes
- `progress.md`：追加真实测试数据创建、延迟响应、删除和清理证据；测试目录已由页面确认型删除接口清理，无测试文件残留。
- 观察到 Axios 主动取消 `/library/browser/files` 时仍输出 `[API Error] ... canceled` 控制台错误；epoch/Abort 行为正确且不影响删除一致性，但日志级别可单独收敛。
- 回滚方式：本轮除进度记录外未修改业务代码；删除本段进度记录即可。运行库中的测试 ledger 按既有 7 天保留策略自动清理，不应手工删除未确认水位记录。

## 2026-07-11 - Task: 静默处理前端主动取消的 API 请求
### What was done
- 在 Axios 响应拦截器记录错误前识别主动取消请求，覆盖 Axios `isCancel`、`ERR_CANCELED`、`CanceledError` 和原生 `AbortError`。
- 取消请求继续以 rejected Promise 透传给调用方维持现有 epoch/loading 收尾逻辑，但不再输出误导性的 `[API Error] ... canceled`。
- 普通网络和接口错误继续进入原有 console、OTP 与安全网关处理分支，不被吞掉。

### Testing
- `cd frontend; npm run test -- --run`：通过，`5` 个测试文件、`16 passed`；新增取消请求四种形态和普通错误不误判测试。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/api/index.js frontend/src/api/apiCancellation.test.js`：通过；仅有既有 LF/CRLF 提示。
- Playwright 打开真实库存页并连续点击两次“刷新”制造 Abort：console `Errors: 0`、`Warnings: 0`，未再出现 canceled 误报。

### Notes
- `frontend/src/api/index.js`：新增 `isCanceledApiRequest()`，并在响应错误拦截器首段静默透传取消请求。
- `frontend/src/api/apiCancellation.test.js`：新增取消分类回归测试。
- `progress.md`：追加本轮修复和真实页面验证记录。
- 回滚方式：反向应用 `frontend/src/api/index.js` 的 `isCanceledApiRequest()` 与拦截器早退分支，删除 `frontend/src/api/apiCancellation.test.js` 和本段进度记录。

## 2026-07-11 - Task: 问题作品重试失败状态收口修复
### What was done
- 复现服务器现象：日志显示 `RJ01610657`、`RJ01650755`、`RJ01592997` 在重试后已解压失败并进入 `waiting_manual`，但问题作品仍保留 `PROCESSING`，前端因此显示“重试中”且进度 `100%`。
- 修复问题作品重试任务收尾：`RETRY` 任务进入 `waiting_manual` 时按重试失败终态处理，原问题项恢复 `PENDING`，写入 `retry_result`、`resolution_error`、`resolution_progress` 和 `resolution_step`。
- 修复 `/api/conflicts` 列表自愈：已有 `PROCESSING + RETRY + linked task waiting_manual` 的历史卡住项，列表加载时自动恢复为待处理，部署后刷新即可收口旧数据。
- 修复最终进度覆盖：`RETRY` 的 `waiting_manual` 进度刷新转成 `failed`，避免收尾写入 `failed` 后又被最终通知覆盖回 `waiting_manual`。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\task_engine.py app\api\routes.py`：通过。
- `git diff --check -- backend/app/core/task_engine.py backend/app/api/routes.py backend/tests/test_task_engine.py`：通过；仅有既有 LF/CRLF 提示。
- 自定义不依赖 PostgreSQL 的项目 venv 脚本验证 `_finalize_conflict_resolution_task()`：模拟 `PROCESSING` conflict + `RETRY` task 进入 `WAITING_MANUAL`，确认 conflict 回到 `PENDING`、`resolution_task_state=failed`、`retry_result=failed`、`resolution_error=无正确密码`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_task_engine.py::TestTaskEngine::test_auto_process_extract_failure_moves_to_waiting_manual tests/test_task_engine.py::TestTaskEngine::test_finalize_conflict_retry_waiting_manual_restores_pending -q --basetemp .pytest-codex-conflict-retry-final2`：未完成；测试库 `kikoerumanager_test` PostgreSQL 连接超时，pytest 在 `conftest.py` 导入阶段失败，未执行用例。

### Notes
- `backend/app/core/task_engine.py`：把问题作品 `RETRY` 的 `waiting_manual` 视为重试失败终态，并避免最终进度刷新继续写 `waiting_manual`。
- `backend/app/api/routes.py`：列表接口对旧 stuck `PROCESSING` retry 项做自愈恢复。
- `progress.md`：追加本轮修复、验证和回滚记录。
- 回滚方式：反向应用 `task_engine.py` 中 `RETRY waiting_manual` 状态转换和 `_finalize_conflict_resolution_task()` 的 waiting_manual 失败收口分支，以及 `routes.py` 中 `_is_retry_waiting_manual_done` 自愈分支；删除本段进度记录。

## 2026-07-12 - Task: 修复 DLsite 历史缓存错误标记导致真实特典永久漏检
### What was done
- 根据服务器 `RJ01192535 / RJ01201745` 现场确认：候选范围已覆盖真实特典，但 PostgreSQL / Redis 旧缓存把符合官方结构的 `RJ01201745` 保存为 `is_hidden_bonus_audio=false`，任务因此把全部候选当已缓存跳过且不再发起 DLsite 请求。
- 将隐藏特典结构判定收敛为统一纯函数，新鲜 `product/info/ajax` 响应、PostgreSQL 缓存和 Redis overlay 都按 `exists / probe_status / maker_id / price / is_sale / is_free / is_oly / wishlist_count` 重新计算，不再永久信任历史布尔标记。
- 保留 DLsite 严格零值语义：若 `raw_summary_json.raw_wishlist_count` 存在则优先使用，布尔 `false` 不按数字 `0` 误判；缺少原始值的旧缓存才回退已归一整数。
- 缓存读取只做内存自愈，不在大范围扫描读路径批量回写数据库，避免一次任务制造上万条额外写入；后续正常命中流程仍会写入命中索引与作品关联。
- 同步特典探测文档，明确历史缓存标记必须按当前结构规则重算。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\dlsite_service.py app\core\dlsite_bonus_probe_service.py tests\test_dlsite_bonus_probe_service.py`：通过。
- 定向缓存与 DLsite 结构回归：`20 passed`；覆盖 PostgreSQL 旧缓存、Redis 旧缓存、`RJ01201745` 空日期形态、布尔 `false` wishlist，以及 missing / 不存在 / 付费 / 在售 / 非免费 / 非 OLY / wishlist 非零防误判。
- RG68316 相关链路串行回归：`4 passed`；覆盖已知特典对、远距离缓存复用和缓存特典计数。
- 使用服务器 `RJ01201745` 真实缓存只读回放：将 `is_hidden_bonus_audio` 在内存模拟回旧 `false` 后，新代码重算为 `true`。
- 完整运行 `test_dlsite_bonus_probe_service.py + test_circle_completion_paged_view.py`：`78 passed, 6 failed`；失败来自测试库并发建删表死锁及其 `relation does not exist` 级联、两个既有测试引用未定义 `fake_next_date_worknos`、分页测试访问当前实现不存在的 `_cover_alias_restore_tasks`，相关缓存命中用例单独串行重跑均通过。
- `git diff --check -- backend/app/core/dlsite_service.py backend/app/core/dlsite_bonus_probe_service.py backend/tests/test_dlsite_bonus_probe_service.py docs/dlsite-bonus-probe.md`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/dlsite_service.py`：新增统一产品探测特典分类纯函数，新鲜响应也复用相同结构规则。
- `backend/app/core/dlsite_bonus_probe_service.py`：PostgreSQL 和 Redis 缓存反序列化后统一重算特典分类。
- `backend/tests/test_dlsite_bonus_probe_service.py`：补历史 DB / Redis 错误标记自愈、严格 wishlist 零值和非特典边界回归。
- `docs/dlsite-bonus-probe.md`：记录历史缓存标记不得作为永久真值。
- `progress.md`：追加本轮根因、实现和验证记录。
- 回滚方式：反向应用上述四个业务文件中 `normalize_product_probe_feature_classification()`、缓存反序列化重算、对应测试和文档 hunk，并删除本段进度记录。

## 2026-07-12 - Task: 修复社团补全底部分页按钮被裁切
### What was done
- 确认分页激活按钮会放大并产生向下阴影，而社团补全标签内容容器使用 `overflow: hidden`，分页行底部没有安全空间，导致按钮底边和阴影被父容器裁切。
- 在社团补全标签页内统一为 `works-pager + km-pagination-wrap` 分页行增加底部安全区，并保留左右轻量间距；缺失作品、已满足作品、来源对比三个分页统一生效。
- 未修改全站分页规范、虚拟列表高度和移动端折行逻辑，避免影响库存、任务中心等其它页面。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/views/CircleCompletion.vue`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：为社团补全标签页内分页行增加 12px 底部安全区，避免激活按钮缩放与阴影被裁切。
- `progress.md`：追加本轮分页裁切修复和验证记录。
- 回滚方式：删除 `.circle-tabs :deep(.works-pager.km-pagination-wrap)` 样式块，并删除本段进度记录。

## 2026-07-12 - Task: 优化社团补全分页激活按钮阴影
### What was done
- 确认灰色块来自全局分页激活态的 `0 10px 22px` 向下阴影和 `scale(1.08)` 放大，在社团补全浅色内容区显得过重。
- 仅覆盖社团补全分页激活态，将阴影收紧为贴边轻阴影与细描边，并把放大幅度降为 `1.04`；同步覆盖 hover，避免悬停时恢复重阴影尺寸。
- 未修改全站分页和暗色模式；库存等其它页面保持原样，暗色分页继续使用既有无外阴影表现。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/views/CircleCompletion.vue`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：收紧社团补全分页激活按钮的阴影和缩放幅度。
- `progress.md`：追加本轮分页视觉优化和验证记录。
- 回滚方式：删除 `.circle-tabs :deep(.works-pager.km-pagination-wrap .el-pagination.is-background .el-pager li.is-active)` 及其 hover 覆盖，并删除本段进度记录。

## 2026-07-12 - Task: 统一已有文件夹页面工作台布局
### What was done
- 将原有纵向处理侧栏重排为状态概览下方的横向操作台，处理概览、四阶段流程、执行选项和批量动作在宽屏并列展示，避免空数据时左右信息严重失衡。
- 为目录区域补充独立工作区标题、扫描结果计数和紧凑空态高度，使页面层级与库存、问题作品等工作台保持一致。
- 修正浅色模式下批量入库、查重和卡片操作按钮的禁用态，改用页面语义灰色，不再出现整块深黑按钮；同步补齐 1280、980、640 三档响应式重排。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/views/ExistingFolders.vue`：通过；仅有既有 LF/CRLF 提示。
- 已通过根目录 `start-all.bat` 启动验证环境，后端 `5555` 正常监听；前端终端停留在交互状态且 `5556` 未监听，因此未完成真实页面截图验证，不将其记为已通过。

### Notes
- `frontend/src/views/ExistingFolders.vue`：重排已有文件夹操作台、目录工作区层级、禁用态和响应式布局。
- `progress.md`：追加本轮视觉优化、构建证据和未完成的页面截图验证说明。
- 回滚方式：反向应用 `frontend/src/views/ExistingFolders.vue` 本轮横向操作台、目录工作区标题、禁用态及响应式样式 hunk，并删除本段进度记录。

## 2026-07-12 - Task: 恢复已有文件夹原布局并调整语义颜色
### What was done
- 按反馈完整撤销上一轮横向操作台、目录工作区标题和新增响应式重排，页面恢复原有左侧策略栏、右侧状态条与目录区域布局。
- 仅调整页面颜色：主操作、开关和选中态统一为青绿色，第二个批量入库动作用靛蓝色区分，保留冲突橙色、成功绿色和危险红色语义。
- 将浅色模式下原本显示为深黑块的禁用按钮改为语义灰色，暗色模式继续复用页面变量，不修改任何扫描、查重或入库逻辑。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/views/ExistingFolders.vue`：通过；仅有既有 LF/CRLF 提示。
- `rg` 检查确认上一轮新增的 `pipeline-section-head`、`folder-workspace-head`、`display: contents` 和 1280px 布局断点均已移除。

### Notes
- `frontend/src/views/ExistingFolders.vue`：恢复原布局，仅保留主色、次操作色、选中态和禁用态颜色调整。
- `progress.md`：追加布局回退与实际颜色调整记录，覆盖上一轮阶段性结论。
- 回滚方式：反向应用 `ExistingFolders.vue` 中 `--ef-primary`、`--ef-accent-*`、`--ef-secondary-*`、按钮文字/阴影及禁用态颜色 hunk，并删除本段进度记录。

## 2026-07-12 - Task: 优化高负荷下系统日志写入与实时刷新
### What was done
- 将应用文件日志和控制台输出改为进程内有界队列异步消费，业务线程不再同步等待日志磁盘写入；队列满时淘汰最旧记录并保留最新日志，避免日志爆量反向阻塞主业务。
- 日志轮转、截断和备份清理会先排空并暂停 listener，文件操作完成后恢复消费，保持 Windows 文件句柄和现有日志管理接口兼容。
- 将全历史检索移到独立 `system-log-search` 执行器，避免占满实时读取的 `system-log-io` 线程；SSE 增量检查正式使用 `runtime_buffer.log_stream_flush_ms`，不再固定等待 1 秒。
- 日志流诊断新增异步 writer、实时读取池和历史搜索池的队列、线程、丢弃及存活状态；明确日志写盘不依赖 Redis，避免 Redis 故障日志递归依赖 Redis。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app/core/app_logging.py app/api/routes.py tests/test_app_logging.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_app_logging.py -q --basetemp .pytest-tmp-codex-logs-async2`：`3 passed`；覆盖队列溢出保留最新记录、listener 停止前排空、真实子进程异步写盘与立即轮转后继续写入。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_redis_config.py -q --basetemp .pytest-tmp-codex-logs-redis`：`19 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_routes_maintenance_config.py -q --basetemp .pytest-tmp-codex-logs-routes`：`32 passed`。
- 使用根目录 `start-all.bat` 重启后运行态验证：后端 `/api/health` 与前端 `5556` 均返回 `200`；日志诊断显示异步 writer 存活、队列 `0/10000`、丢弃 `0`，实时与历史执行器分别为 `2`、`1` worker。
- 真实请求 `/api/logs/search` 成功扫描主日志并返回结果；连接 `/api/logs/stream?lines=50` 在 2 秒窗口内收到 `connected` 首包，断开后 `active_streams=0`、`total_connections=1`。
- `git diff --check -- backend/app/core/app_logging.py backend/app/api/routes.py backend/tests/test_app_logging.py docs/runtime-buffer-control-plane.md`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/app_logging.py`：新增有界非阻塞日志队列、后台 listener、运行态诊断，并兼容轮转、截断和进程退出排空。
- `backend/app/api/routes.py`：隔离实时日志与历史检索执行器，接通 SSE flush 配置并扩展日志诊断。
- `backend/tests/test_app_logging.py`：新增异步写盘、队列溢出和日志轮转回归测试。
- `docs/runtime-buffer-control-plane.md`：补充异步写盘、线程池隔离、诊断字段和不使用 Redis 的原因。
- `progress.md`：追加本轮日志高负荷优化、验证和回滚记录。
- 回滚方式：反向应用 `app_logging.py` 的队列 listener、`routes.py` 的 `_LOG_SEARCH_EXECUTOR`、`poll_interval` 和 writer 诊断 hunk，删除 `test_app_logging.py`，反向应用运行态缓冲文档对应段落，并删除本段进度记录。

## 2026-07-12 - Task: 优化大文本系统日志搜索与分页
### What was done
- 将全历史日志搜索的数字匹配偏移改为不透明文件游标，游标携带查询签名、文件快照和字节位置；下一页从上次位置续扫，不再从文件头重复扫描并跳过旧命中。
- 日志轮转、截断、查询条件或扫描窗口变化时自动失效旧游标并从最新快照重启，前端同步清空分页历史，避免把不同日志世代的结果拼在一起。
- 浏览器取消检索后，后端通过协作取消信号终止仍在独立搜索线程中的扫描，避免旧请求继续占用唯一搜索 worker。
- 将单行读取限制为 64KB 片段，支持关键词跨片段边界命中；无换行巨型日志不会再被 `readline()` 一次读入内存，响应单条仍限制为 16KB。
- 前端使用游标栈实现上一页与下一页，保留页起点匹配数展示，不再用数字页偏移触发后端全量重扫。
- 修复运行态暴露的日志启动反压：文件日志继续异步写盘，控制台输出从文件 listener 拆出，终端阻塞不会再卡住文件日志消费和后端启动。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_log_search.py -q --basetemp .pytest-tmp-codex-log-search`：`4 passed`；覆盖连续三页无漏项、64KB 边界关键词、取消停扫和截断后游标失效。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_log_search.py tests/test_app_logging.py tests/test_routes_maintenance_config.py -q --basetemp .pytest-tmp-codex-log-search-all`：`39 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_app_logging.py tests/test_log_search.py -q --basetemp .pytest-tmp-codex-log-startup-fix`：`7 passed`。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- 使用根目录 `start-all.bat` 重启后 `/api/health` 返回 `200`，文件异步 writer 正常写入启动日志。
- 使用本机约 `52MB` 的 `app.log + app.log.1 + app.log.2` 验证：稀有词跨 3 文件完整扫描成功；高频词连续两页分别返回 50 条，第二页 `matched_before=50`，首条紧接第一页末条，游标未重置。

### Notes
- `backend/app/api/routes.py`：新增日志搜索游标、文件快照、分片扫描和协作取消，并替换原数字 offset 搜索实现。
- `backend/app/core/app_logging.py`：控制台输出与文件异步 listener 解耦，避免终端反压阻断文件日志和启动。
- `backend/tests/test_log_search.py`：新增大文本搜索分页、超长行、取消和轮转边界回归。
- `frontend/src/api/index.js`：日志搜索 cursor 默认值改为字符串。
- `frontend/src/views/Logs.vue`：接入不透明游标和页面游标历史。
- `docs/runtime-buffer-control-plane.md`：补充大文本搜索游标、取消和有界分片设计。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `routes.py` 的 `_LOG_SEARCH_CURSOR_VERSION` 至 `_search_log_snapshots()` 及 `search_logs()` 游标实现，恢复前端数字 cursor 分页，删除 `test_log_search.py`，反向应用 `app_logging.py` 的控制台解耦和对应文档段落，并删除本段进度记录。

## 2026-07-12 - Task: 修复日志筛选布局并增加关键词高亮
### What was done
- 将日志筛选区从自由挤压的 flex 布局改为“级别、模块、搜索、操作组”四区网格，窄屏自动切为两列和单列，条数、全历史搜索与精简过程统一收进操作组。
- 移除搜索框清空按钮固定 `right: 86px` 的错误定位：普通搜索时贴右 7px，全历史模式时为“清空 + 检索”分别预留位置，两按钮保持 7px 间距。
- 日志终端新增关键词分段高亮，普通搜索和全历史搜索共用当前搜索词；折叠行、展开原始日志和任务进度行均支持高亮，仍保持文本节点渲染，不使用 `v-html`。
- 高亮只对虚拟列表当前可见行即时拆分，不为全部历史结果预生成 HTML，避免搜索 500 条大文本时增加常驻内存。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- 本地浏览器验证普通搜索：输入 `LocalScanner` 后可见区生成 `25` 个高亮标记；浅色和暗色模式布局正常，清空按钮距离搜索框右侧均为 `7px`。
- 本地浏览器验证全历史模式：清空按钮右侧预留 `72px`，检索按钮距离右侧 `5px`，两按钮间距 `7px`，无重叠；搜索结果继续显示 `25` 个可见高亮。
- `git diff --check -- frontend/src/views/Logs.vue frontend/src/components/common/SystemLogTerminal.vue`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/views/Logs.vue`：重排日志筛选工具栏，修正搜索框内按钮定位，并向终端传递搜索词。
- `frontend/src/components/common/SystemLogTerminal.vue`：新增安全文本分段高亮和高亮样式。
- `progress.md`：追加本轮日志 UI 优化、验证与回滚记录。
- 回滚方式：反向应用 `Logs.vue` 的四区网格、搜索框按钮定位和 `highlight-terms` 传参，反向应用 `SystemLogTerminal.vue` 的 `highlightTerms`、`highlightedTextParts()`、模板 mark 节点及 `.terminal-search-highlight` 样式，并删除本段进度记录。

## 2026-07-12 - Task: 强化社团补全作品整体选中态
### What was done
- 保留作品卡片原有底色和封面色彩，移除选中时对卡片背景与封面滤镜的改色，仅通过整卡蓝色描边、内圈和轻量外光表达选中状态。
- 将卡片选中描边加粗并修正到卡片内部，避免被绘制裁切；顶部蓝色状态条同步加强，暗色模式改为一致的蓝色整卡选中态且不覆盖原卡片背景。
- 列表模式同步取消选中背景改色，只保留整行边框、左侧蓝条与轻量外圈，确保卡片和列表交互语义一致。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue`：通过；仅有既有 LF/CRLF 提示。
- `rg` 检查确认卡片与列表的普通选中规则、暗色卡片选中规则均不再设置 `background`，卡片选中规则也不再修改封面 `filter`。

### Notes
- `frontend/src/components/circle/WorkCard.vue`：保留卡片本色，改为整卡描边、内圈、外光和顶部状态条表达选中态，并同步暗色模式。
- `frontend/src/components/circle/WorkListRow.vue`：保留列表行本色，仅强化整行选中边界。
- `progress.md`：追加本轮选中态修正、验证与回滚记录。
- 回滚方式：反向应用 `WorkCard.vue` 中选中光环、选中卡片及暗色选中态 hunk，反向应用 `WorkListRow.vue` 的选中态 hunk，并删除本段进度记录。

## 2026-07-12 - Task: 修复社团补全选中计数与卡片状态不同步
### What was done
- 修复作品使用关联显示 RJ 时，选中集合保存 canonical RJ、视口却只按显示 RJ 判断，导致“已选数量增加但卡片没有 selected 状态”的问题。
- 卡片与列表的选中、状态闪烁和搜索定位统一同时匹配 canonical RJ、显示 RJ、作品 RJ 与来源对比 RJ；特典聚合成员也使用同一套匹配规则。
- 保留上一轮整卡描边方案，选中状态命中后由卡片四周蓝色描边、内圈、外光和顶部状态条显示，不改变原卡片底色。

### Testing
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `git diff --check -- frontend/src/components/circle/CircleWorksViewport.vue frontend/src/components/circle/WorkCard.vue frontend/src/components/circle/WorkListRow.vue`：通过；仅有既有 LF/CRLF 提示。
- 差异检查确认普通作品、聚合特典、卡片模式和列表模式均改用统一作品代码集合匹配状态。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：统一 canonical、显示及关联 RJ 的选中/闪烁/定位状态匹配。
- `progress.md`：追加本轮状态传递根因、验证与回滚记录。
- 回滚方式：反向应用 `CircleWorksViewport.vue` 中 `workStateCodeList`、`matchesWorkCodeSet` 及相关状态判断 hunk，并删除本段进度记录。

## 2026-07-12 - Task: 修复日志续行时间戳缺失
### What was done
- 修复尾部日志窗口从 Python traceback 中间截断时无法找到异常主日志、整屏续行显示 `--:--:--` 的问题。
- 后端仅在尾窗没有结构化日志边界时额外向前补读最多 512KB，找到 traceback 所属的真实时间和级别后再折叠，普通尾读成本不变。
- 前端让普通续行继承上一条结构化日志时间；窗口开头的续行可继承下一条结构化日志时间，完全没有上下文时仍保持空时间。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_routes_maintenance_config.py tests/test_log_search.py tests/test_app_logging.py -q --basetemp .pytest-tmp-codex-log-time-all`：`40 passed`；覆盖 400 行 traceback 仅取末尾 100 行仍保留 `2026-07-12 15:00:00` 和 `ERROR`。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- 使用根目录 `start-all.bat` 重启后，`GET /api/health` 返回 `200`，`GET /api/logs?lines=300` 正常返回带时间的结构化日志。
- 本地浏览器验证日志页：当前虚拟窗口渲染 `25` 个 `.terminal-time` 节点，缺失时间节点为 `0`，未出现 `--:--:--`。

### Notes
- `backend/app/api/routes.py`：尾读窗口缺少结构化边界时有限向前补读 traceback 上下文。
- `backend/tests/test_routes_maintenance_config.py`：新增长 traceback 尾窗时间与级别回归。
- `frontend/src/views/Logs.vue`：为日志续行补充前后结构化时间继承。
- `docs/runtime-buffer-control-plane.md`：记录 traceback 尾窗补读与时间继承规则。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `routes.py` 中 `_tail_lines()` 的有限上下文补读、`Logs.vue` 中 `parseLogLines()` 的时间继承、删除对应测试和文档段落，并删除本段进度记录。

## 2026-07-12 - Task: 收紧封面、搜索建议与群晖容量慢请求
### What was done
- 社团封面本地缺失时立即返回 `404` 并创建按文件名去重的后台补图任务，前端继续使用既有 DLsite fallback，图片请求不再同步等待 CDN；同时补齐历史展示 RJ 封面别名恢复任务的实例状态。
- 跨库搜索 `mode=suggest` 只读取库存索引，未就绪的远程库标记为 `skipped_suggest`，不再触发固定 5 秒的群晖搜索兜底。
- 群晖库存容量改为按库存根路径对应 share 的 `volume_status` 读取所属卷容量，不再累加整台群晖所有卷；同库并发刷新合并为 singleflight，有旧缓存最多等待 350ms，冷请求最多等待 2s。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py::test_paged_works_cover_cache_url_uses_image_file_rjcode -q --basetemp .pytest-tmp-codex-verify`：`1 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_synology_remote_health.py tests\test_circle_completion_paged_view.py tests\test_routes_maintenance_config.py -q --basetemp .pytest-tmp-codex-full`：`59 passed`；覆盖 share 卷容量映射、未知 share 拒绝、容量 singleflight、suggest 禁止 fallback、封面缺失后台调度与去重。
- 使用项目运行配置只读连接真实群晖验证：库存根路径 `/ASMR` 匹配 share `ASMR`，返回 `storage_scope=share_volume`、单卷 `total_size_bytes=15349525921792`、`free_size_bytes=3425589309440`，未再累加其它卷。

### Notes
- `backend/app/api/routes.py`：新增群晖容量冷请求截止与刷新 singleflight，suggest 模式跳过远程 fallback，封面缺失改为后台调度。
- `backend/app/core/library_manager.py`：按库存根路径匹配群晖 share，并从 `volume_status` 返回单卷容量。
- `backend/app/core/circle_image_cache_service.py`：新增缺失封面的后台去重补齐入口。
- `backend/app/core/circle_completion_service.py`：补齐历史封面别名恢复任务和待处理集合的实例状态。
- `backend/tests/test_synology_remote_health.py`：新增 share 容量映射与未知 share 回归测试。
- `backend/tests/test_circle_completion_paged_view.py`：新增后台补图去重测试，并验证历史别名恢复任务。
- `backend/tests/test_routes_maintenance_config.py`：新增容量 singleflight、suggest 快路径和封面缺失调度回归测试。
- `docs/circle-completion-performance-cache.md`：更新封面缺失时的非阻塞行为。
- `docs/library-remote-read-performance.md`：记录远程搜索建议与群晖容量统计、缓存、超时契约。
- `progress.md`：追加本轮实现、验证与回滚边界。
- 回滚点：仅反向应用本轮 `_LIBRARY_STORAGE_INFO_COLD_TIMEOUT_SECONDS` / `_LIBRARY_STORAGE_INFO_REFRESH_TASKS`、`skipped_suggest` / `fallback_attempted`、`schedule_ensure_for_filename()`、`get_storage_info(root_path)` 与 `_cover_alias_restore_*` 对应 hunk，删除本轮新增测试和 `docs/library-remote-read-performance.md`，恢复封面文档原句，并删除本段进度记录；不要回退这些共享文件中的其它未提交改动。

## 2026-07-12 - Task: 百度网盘持续低速自动换链并复用旧断点
### What was done
- 为 SVIP 大文件下载增加基于真实下载字节增量的持续低速检测；默认文件不少于 512 MiB、连续 180 秒低于 3 MB/s 时触发换链。
- 换链仅终止当前 BaiduPCS-Go 子进程，保持同一个远端临时转存目录、工作目录和 savedir，重新执行 locate 获取线路并复用 `.BaiduPCS-Go-downloading` 旧断点，不重复转存分享文件。
- 单文件默认最多换链 2 次；达到上限后关闭低速中止并保留当前断点继续下载，避免无限重试。续传输出若从零重新计数，会叠加旧断点字节，保证任务进度不倒退。
- 下载运行态新增换链次数、换链上限、断点字节、低速窗口速度和换链状态；设置页新增开关、阈值、持续时间和最大换链次数。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_baidu_netdisk_service.py -q --basetemp backend/.pytest-tmp-baidu`：`53 passed`；覆盖低速窗口、真实子进程中止、同 savedir 连续两次换链、旧断点存在、续传进度偏移和最终不无限重试。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_baidu_netdisk_service.py backend\tests\test_baidu_netdisk_account_api.py backend\tests\test_task_notification_service.py backend\tests\test_routes_maintenance_config.py -q --basetemp backend/.pytest-tmp-baidu-final`：`97 passed`。
- `cd frontend; npm.cmd run build`：通过，`4183 modules transformed`，预压缩完成。
- 项目 Python `py_compile` 覆盖百度下载服务、配置模型和测试文件；`git diff --check` 通过，仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/baidu_netdisk_service.py`：新增持续低速检测、子进程内部中止、同目录 locate 换链、断点进度偏移和运行态字段。
- `backend/app/config/settings.py`、`backend/config/config.yaml`：新增低速换链默认配置。
- `backend/tests/test_baidu_netdisk_service.py`：新增低速判定、子进程中止、换链上限和旧断点续传回归。
- `frontend/src/components/settings/BaiduNetdiskSettingsPanel.vue`：新增持续低速自动换链设置项。
- `docs/baidu-netdisk-low-speed-refresh.md`：记录换链、断点复用、配置和运行态契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：仅反向应用上述文件中的 `low_speed_*`、`link_refresh_*`、`BaiduNetdiskLowSpeedError`、`abort_check` 和对应设置页 / 测试 / 文档 hunk，并删除本段进度记录；不要回退这些共享文件中的其它未提交改动。

## 2026-07-12 - Task: 百度分享转存串行化并补强 SSL EOF 恢复
### What was done
- 百度分享 `/share/transfer` 新增独立全局转存槽，默认只允许 1 个请求执行；转存完成立即释放，不改变 BaiduPCS-Go 每文件 20 线程及现有全局下载文件数限制。
- 转存遇到 SSL EOF、连接/读取超时、HTTP 429 或 5xx 时，使用新 Session、新 `logid` 和新 `dp-logid` 按 2、5、12、30 秒退避重试；分享失效、提取码错误等业务错误不重试，取消或暂停可立即中断等待。
- 网络响应丢失后先查询远端临时目录，只有文件名和精确字节数一致才确认实际转存成功并继续下载；不匹配时继续正常重试。
- 任务运行态新增转存等待、执行、重试、尝试次数和下次等待时间；错误日志补齐 `sekey`、`logid`、`dp-logid`、`randsk`、`bdstoken` 脱敏，设置页开放转存并发与网络重试次数。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_baidu_netdisk_service.py -q --basetemp backend/.pytest-tmp-baidu-transfer`：`61 passed`；覆盖 8 文件转存峰值并发为 1、SSL EOF 重试与请求标识刷新、业务错误不重试、取消中断、个人网盘精确列表确认、BaiduPCS-Go 兜底确认、大小不匹配拒绝和敏感参数脱敏。
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_baidu_netdisk_service.py backend\tests\test_baidu_netdisk_account_api.py backend\tests\test_task_notification_service.py backend\tests\test_routes_maintenance_config.py -q --basetemp backend/.pytest-tmp-baidu-transfer-final`：`105 passed`。
- `cd frontend; npm.cmd run build`：通过，`4183 modules transformed`，预压缩完成。
- 项目 Python `py_compile` 覆盖百度下载服务和配置模型；`git diff --check` 通过，仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/baidu_netdisk_service.py`：新增转存槽、瞬时网络重试、远端结果确认、运行态和错误脱敏。
- `backend/app/config/settings.py`、`backend/config/config.yaml`：新增转存并发与重试默认配置。
- `backend/tests/test_baidu_netdisk_service.py`：新增转存并发、重试、取消、确认和脱敏回归测试。
- `frontend/src/components/settings/BaiduNetdiskSettingsPanel.vue`：新增转存并发与重试次数设置项。
- `docs/baidu-netdisk-low-speed-refresh.md`：补充转存稳定性、下载限制不变和运行态契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：仅反向应用上述文件中的 `transfer_*`、`_acquire_global_transfer_slot()`、`_transfer_share_item_with_retry()`、`_confirm_remote_temporary_transfer_file()`、转存敏感参数脱敏及对应设置页 / 测试 / 文档 hunk，并删除本段进度记录；不要回退共享文件中的低速断点续传或其它未提交改动。

## 2026-07-12 - Task: 修复社团补全 DLsite 身份发现与预告污染
### What was done
- 将未知社团的身份发现改为解析 DLsite 搜索结果中的真实作品链接和 maker profile 链接，不再依赖库存，也不再对整个 HTML 页面扫描所有 RJ。
- 名称匹配后只接受唯一 `RG` maker ID；同名对应多个 maker ID 时明确拒绝自动选择，支持直接输入 `RG` 或包含 maker ID 的 DLsite 链接。
- maker ID 确认后继续复用现有 maker profile、maker announce、音声分类和元数据链路；已有 maker ID 的社团完全跳过身份搜索，保持原快速路径。
- 预告搜索仅接收包含名称匹配 maker 链接的结构化作品结果；官方入口正常但无匹配时不请求 `home-touch`，网络失败回退时也会拒绝全站默认预告页。
- 搜索与预告同时网络失败且没有任何结构化候选时返回“DLsite 社团搜索暂时不可用”，不再误报为社团名称无效。

### Testing
- `cd backend; .\venv\Scripts\python.exe -m py_compile app/core/circle_completion_service.py tests/test_circle_completion_announce_search.py tests/test_circle_completion_maker_discovery.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests/test_circle_completion_announce_search.py tests/test_circle_completion_maker_discovery.py tests/test_circle_completion_paged_view.py tests/test_circle_completion_bonus_grouping.py -q --basetemp .pytest-tmp-codex-maker-final`：`31 passed`。
- 使用项目实际 DLsite 客户端在线冒烟：搜索 `おほ声の館` 首页提取 30 个真实作品链接，唯一身份解析为 `RG62099`，无失败原因。
- `git diff --check -- backend/app/core/circle_completion_service.py backend/tests/test_circle_completion_announce_search.py backend/tests/test_circle_completion_maker_discovery.py docs/circle-completion-performance-cache.md`：通过；仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/circle_completion_service.py`：新增结构化搜索页解析、唯一 maker 身份选择、直接 RG 输入、安全预告回退和外部不可用错误语义。
- `backend/tests/test_circle_completion_announce_search.py`：将预告回归改为结构化 maker 匹配，并覆盖主入口超时后拒绝全站默认页。
- `backend/tests/test_circle_completion_maker_discovery.py`：新增页面噪音拒绝、同名 maker 歧义、无库存身份发现及已有 maker 快速路径回归。
- `docs/circle-completion-performance-cache.md`：补充不依赖库存的 DLsite 身份发现、唯一性验证和安全降级约束。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `circle_completion_service.py` 的 `_extract_dlsite_search_page_identity()`、`_choose_dlsite_maker_identity()`、两条搜索返回结构及 `_collect_dlsite_circle_candidates()` 身份发现 hunk，恢复预告测试旧签名，删除 `test_circle_completion_maker_discovery.py`，反向应用对应文档段落，并删除本段进度记录。

## 2026-07-12 - Task: 收口字幕工作台关闭竞态并完成延后归档迁移验证
### What was done
- 字幕工作台扫描、可用性检查、目录状态、任务状态和检查器读取统一接入会话 token 与 AbortSignal；关闭时先失效会话并中止请求，晚到扫描回调、自动入队和任务创建不再继续写回当前工作台。
- 取消与清理拆开：先取消活跃字幕任务，再等待 worker 退出 processing 集合并有限重试清理；冲突不再静默吞掉，未退出任务保留供后续重试。
- 修复字幕可用性接口重复 Axios config，并让 `/rj-subtitle/start`、`/rj-subtitle/status` 正确透传取消信号。
- 补齐旧版库存 rename/delete/batch-delete 与批量 API 重命名后的字幕目录摘要缓存失效；修复 Redis L2 key 混入进程内 generation 导致跨实例无法命中的问题，Redis 共享版本不可用时才使用本地 generation。
- 在本机隔离 PostgreSQL 测试库 `kikoerumanager_archive_migration_test` 完成延后归档迁移 upgrade、downgrade、upgrade，并核对 revision、表、JSONB 字段和索引。
- 延后归档补充 worker 启停、前台任务到达时让出 lease、双 owner 防并发认领和同名目标后缀预留回归。

### Testing
- `cd frontend; npm test -- --run src/api/apiCancellation.test.js`：`6 passed`。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。
- `cd backend; .\venv\Scripts\python.exe -m py_compile app\core\rj_subtitle_service.py app\core\linked_subtitle_import_service.py app\core\task_engine.py app\api\routes.py`：通过。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_linked_subtitle_import_service.py tests\test_task_engine.py -q --basetemp .pytest-tmp-subtitle-rerun`：`57 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_task_engine_cancellation.py -q --basetemp .pytest-tmp-task-cancellation`：`2 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_deferred_archive_service.py tests\test_processed_archive_cleanup.py tests\test_archive_volume_utils.py tests\test_processed_archives_scan.py tests\test_task_engine.py tests\test_task_engine_cancellation.py -q --basetemp .pytest-tmp-archive-final`：`48 passed`；覆盖 worker 启停、前台抢占、双 owner lease、目标冲突、过期 lease 恢复和归档完成链路。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_library_index_self_mutation.py tests\test_library_index_remote_scanner.py tests\test_library_index_mutation_service.py tests\test_library_index_generation.py -q --basetemp .pytest-tmp-library-index`：`44 passed`。
- `cd backend; .\venv\Scripts\python.exe -m pytest tests\test_library_browser_api.py::test_legacy_library_mutations_invalidate_subtitle_folder_summary_cache -q --basetemp .pytest-tmp-library-routes`：`1 passed`。
- 隔离 PostgreSQL：全新库升级到 `20260712_0001_deferred_archive_queue`；降级后 `deferred_archive_jobs` 与 `processed_archives.archive_manifest` 均不存在；重新升级后队列表 17 列、`archive_manifest` 为 JSONB、4 个指定索引齐全。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/views/Library.vue`：新增字幕选择会话取消边界、关闭时取消/等待清理、自动入队与任务创建的 token/signal 复核。
- `frontend/src/api/index.js`：修复重复 Axios config，并为字幕 start/status/availability/folder-state/scan 透传 signal。
- `frontend/src/composables/useSubtitleTask.js`：字幕状态刷新支持取消且取消后不写回任务状态。
- `frontend/src/api/apiCancellation.test.js`：覆盖字幕查询、状态和创建接口的取消信号透传。
- `backend/app/api/routes.py`：补齐旧库存写接口和批量 API 重命名的目录摘要缓存失效。
- `backend/app/core/linked_subtitle_import_service.py`：修正 Redis 共享版本与本地 generation 的缓存 key 语义，并保留失效期间慢扫描不回写旧缓存。
- `backend/tests/test_linked_subtitle_import_service.py`：新增失效期间 inflight 结果不缓存回写测试。
- `backend/tests/test_task_engine_cancellation.py`：新增取消终态不可被 complete/fail 覆盖、processing 集合未退出不可清理测试；避免修改用户标记为 skip-worktree 的原测试文件。
- `backend/tests/test_deferred_archive_service.py`：新增 worker 启停、前台抢占释放 lease、双 owner 防重复认领和同名目标预留回归。
- `backend/tests/test_library_browser_api.py`：新增旧库存写接口缓存失效回归。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：仅反向应用上述文件中字幕 session/AbortSignal、取消后清理重试、旧库存接口缓存失效、`_target_folder_summary_has_shared_version()` 与对应测试 hunk，并删除本段进度记录；不要回退延后归档、字幕缓存基础或共享文件中的其它未提交改动。隔离测试库可单独删除，不影响运行库。

## 2026-07-13 - Task: 优化库存搜索建议结果与悬停稳定性
### What was done
- 完整 RJ 搜索会按真实收录位置折叠结果：保留作品根目录、同库不同位置和多库副本，隐藏继承同一 RJ 的特典、台本、图片等后代目录；同步建议接口和全屏流式搜索使用同一规则。
- 搜索框失焦关闭改为尊重鼠标所在区域，鼠标进入搜索区域会取消待执行的关闭；输入框与下拉之间新增 8px 可悬停桥接区，离开后再延迟收起。
- 补充后端目录折叠和前端失焦悬停回归测试，并同步搜索读路径文档。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_routes_maintenance_config.py -q --basetemp backend/.pytest-tmp-library-search`：`37 passed`。
- `cd frontend; npm.cmd test -- --run src/components/library/LibrarySearchBox.test.js`：`1 passed`。
- `cd frontend; npm.cmd run build`：通过，`4183 modules transformed`，预压缩完成。
- 使用本地运行页面 `http://localhost:5556/library` 验证完整 RJ `RJ01649758` 仅展示作品根目录并显示“命中 1”；页面控制台无 error。
- 项目 Python `py_compile` 覆盖 `backend/app/api/routes.py`；`git diff --check` 通过，仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/api/routes.py`：新增完整 RJ 后代目录折叠，并接入同步与流式跨库搜索结果收口。
- `backend/tests/test_routes_maintenance_config.py`：覆盖同一作品后代折叠、同库不同位置和多库副本保留。
- `frontend/src/components/library/LibrarySearchBox.vue`：新增搜索区域悬停状态、失焦延迟关闭和下拉间隙桥接区。
- `frontend/src/components/library/LibrarySearchBox.test.js`：覆盖鼠标已进入搜索区域时失焦不提前收起、真正离开后关闭。
- `docs/library-remote-read-performance.md`：记录完整 RJ 结果折叠和搜索建议悬停契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `_collapse_exact_rj_descendants()` 及两个调用点，移除 `LibrarySearchBox.vue` 的 pointer/blur/bridge hunk，删除 `LibrarySearchBox.test.js`，反向应用对应测试与文档 hunk，并删除本段进度记录。

## 2026-07-13 - Task: 优化库存移动窗口索引导航与移动预检
### What was done
- 新增移动窗口版本化导航快照：一次返回当前目录和祖先展开节点，索引可用时不再逐项读取磁盘属性；Redis 按库存、索引 generation、view revision 和请求参数做短缓存，失败时直接回 PostgreSQL 索引。
- 移动冲突预检改为索引子树优先，保留顶层真实文件系统校验；目录合并、文件冲突、类型冲突和非法子目录目标使用现有业务语义，超大子树、索引缺失或磁盘不一致时回退原文件系统预检。
- 预检结果生成短期 Redis 移动计划并绑定请求与索引版本；明确过时返回 409，Redis 不可用或计划过期不阻断真实移动；已登记的相同幂等请求优先回放，避免网络重试重复移动或被过期计划误伤。
- 移动窗口接入 AbortSignal、请求 token 和索引视图版本校验，旧请求、跨库晚到请求及旧 revision 不再覆盖当前目录；移动完成后等待索引 fence 物化再普通刷新，8 秒超时才回退强制刷新。
- 索引冲突比较按运行平台文件名大小写语义处理，并补齐导航缓存、旧快照、移动计划、幂等竞态和 Windows 大小写冲突回归。

### Testing
- `$env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'; backend\venv\Scripts\python.exe -m pytest backend\tests\test_library_browser_api.py backend\tests\test_routes_maintenance_config.py -q --basetemp backend/.pytest-tmp-library-move-final-2`：`71 passed`。
- `cd frontend; npm.cmd test -- --run`：`7` 个测试文件、`21 passed`。
- `cd frontend; npm.cmd run build`：通过，`4183 modules transformed`，预压缩完成。
- 项目 Python `py_compile` 覆盖 `backend/app/core/library_manager.py` 和 `backend/app/api/routes.py`。
- 本地运行页面验证移动弹窗可正常打开且索引目录完成加载；导航快照接口首次返回 `cache_source=postgresql`，同版本再次请求返回 `cache_source=redis`，新浏览器控制台无 error。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `backend/app/core/library_manager.py`：新增索引导航快照、Redis 短缓存、索引子树冲突预检、移动计划版本校验和平台文件名比较。
- `backend/app/api/routes.py`：新增导航快照接口、移动计划透传校验及幂等结果优先回放。
- `backend/tests/test_library_browser_api.py`：覆盖导航 Redis 缓存、索引预检、计划过时、幂等并发和大小写冲突语义。
- `frontend/src/api/index.js`、`frontend/src/api/apiCancellation.test.js`：接入导航快照、目录请求取消信号和移动计划字段，并验证请求透传。
- `frontend/src/components/library/LibraryMoveDialog.vue`、`frontend/src/components/library/LibraryMoveDialog.test.js`：接入一次性索引树快照、版本缓存、请求竞态保护、旧快照降级和移动计划提交。
- `frontend/src/views/Library.vue`：移动完成后按索引 fence 等待物化，超时才强制刷新。
- `docs/library-remote-read-performance.md`：记录导航、Redis、索引预检、降级、幂等和 fence 刷新契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `navigation_snapshot_via_index()`、`_preview_move_local_items_via_index()`、移动计划校验及对应路由 hunk，移除 `LibraryMoveDialog.vue` 的快照/token/version 逻辑和 `Library.vue` 的 fence 等待，删除 `LibraryMoveDialog.test.js` 中对应测试并反向应用 API、后端测试和文档 hunk；不要回退同一共享文件中的库存搜索建议优化或其它未提交改动。

## 2026-07-13 - Task: 修复社团补全附属特典卡封面破图
### What was done
- 附属特典卡的小图加载失败时立即切换到同一特典主图，解决本地 `_sam` 缓存首次返回 404 后持续显示浏览器破图图标的问题。
- 主图回退仍失败时改为礼物占位；社团作品数据刷新后清空失败态，允许重新加载已经补齐的缓存。
- 卡片、列表、虚拟滚动和移动端普通渲染四条附属特典展示路径统一使用相同回退行为。

### Testing
- `cd frontend; npx vitest run --config vitest.config.js src/components/circle/CircleWorksViewport.test.js`：`1 passed`，覆盖小图失败回退主图、主图失败显示占位。
- `cd frontend; npm run build`：通过，`4183 modules transformed`，预压缩完成。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：新增附属特典封面失败态和小图到主图的回退处理。
- `frontend/src/components/circle/CircleWorksViewport.test.js`：新增附属特典封面回退回归测试。
- `docs/circle-completion-performance-cache.md`：补充附属特典卡封面缓存失败时的前端展示契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `CircleWorksViewport.vue` 中 `failedBonusImageKeys`、`onBonusCoverLoad()`、`onBonusCoverError()` 及四处模板事件改动，删除 `CircleWorksViewport.test.js`，反向应用封面缓存文档对应条目，并删除本段进度记录。

## 2026-07-13 - Task: 优化社团补全大页滚动性能
### What was done
- 宽屏卡片视图在单页不少于 50 条或达到 6 列以上时，把虚拟列表预渲染范围从两行收紧为一行，避免超宽屏一次挂载几十张额外卡片。
- 滚动期间暂停卡片过渡、封面闪光和附属特典常驻动画，停止滚动 120ms 后恢复；社团补全视口内的作品卡不再永久占用 `will-change` 合成图层；小屏普通布局通过 `content-visibility` 跳过屏外卡片绘制。
- 新增 100 条宽屏数据回归，确认只挂载可见行和一行预渲染卡片，并验证滚动态样式开关。

### Testing
- `cd frontend; npx vitest run --config vitest.config.js src/components/circle/CircleWorksViewport.test.js src/utils/circleCompletionOwnedState.test.js`：`2` 个测试文件、`4 passed`。
- `cd frontend; npm test -- --run`：`9` 个测试文件、`25 passed`。
- `cd frontend; npm run build`：通过，`4184 modules transformed`，预压缩完成。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/components/circle/CircleWorksViewport.vue`：收紧宽屏大页 overscan，增加低频滚动态并暂停高成本视觉效果。
- `frontend/src/components/circle/CircleWorksViewport.test.js`：新增 100 条宽屏虚拟挂载上限和滚动态回归。
- `docs/circle-completion-paged-loading.md`：记录大页虚拟渲染、滚动动效和合成图层约束。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：反向应用 `virtualOverscan`、`viewportScrolling`、`handleViewportScroll()`、滚动容器事件及 `.is-scrolling` / `will-change` 样式 hunk，删除对应大页测试和文档段落，并删除本段进度记录；保留同文件中的附属特典封面回退修复。

## 2026-07-13 - Task: 修复手动刷新拥有态后的缺失与已满足迁移
### What was done
- 刷新任务完成并重读当前分页后，使用任务结果中的 `local_owned / has_kikoeru` 做最终对账，避免旧分页快照把状态已变化的作品继续留在错误 Tab。
- 普通作品和附属特典使用统一分组语义：任一附属成员变为已拥有时，整个作品组从缺失页移除并进入已满足语义；反向变化同样处理。
- 对账时同步当前分页总数、缺失/已拥有统计和选择集合，已迁移作品不会继续保留选中态。

### Testing
- `cd frontend; npx vitest run --config vitest.config.js src/components/circle/CircleWorksViewport.test.js src/utils/circleCompletionOwnedState.test.js`：`2` 个测试文件、`4 passed`；覆盖普通作品和附属特典的拥有态迁移。
- `cd frontend; npm test -- --run`：`9` 个测试文件、`25 passed`。
- `cd frontend; npm run build`：通过，`4184 modules transformed`，预压缩完成。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。

### Notes
- `frontend/src/views/CircleCompletion.vue`：刷新任务完成后执行拥有态最终对账，并同步分页统计与选择态。
- `frontend/src/utils/circleCompletionOwnedState.js`：新增普通作品与附属特典分组的拥有态对账逻辑。
- `frontend/src/utils/circleCompletionOwnedState.test.js`：覆盖缺失转已满足和附属特典带动作品组迁移。
- `docs/circle-completion-paged-loading.md`：记录手动刷新任务结果的前端最终对账契约。
- `progress.md`：追加本轮实现、验证与回滚记录。
- 回滚方式：移除 `reconcileRefreshedOwnedState()` 及刷新任务完成后的调用，删除 `circleCompletionOwnedState.js` 和对应测试，反向应用文档拥有态对账条目，并删除本段进度记录；不要回退同文件中的社团补全分页、任务轮询或其它未提交改动。
