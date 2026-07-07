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
