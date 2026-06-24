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

