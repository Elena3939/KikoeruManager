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
