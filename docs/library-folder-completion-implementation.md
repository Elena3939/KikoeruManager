# 库存页“补全文件夹”实现文档

## 功能目标

在库存页新增“补全文件夹”能力：用户单选或批量选择本地库存目录后，系统识别 RJ 文件夹并检查 ASMR.one 是否有该 RJ 的资源；按解压过滤规则过滤远端文件表，再与本地目录内已有文件对比，只下载缺失文件。若选中的是社团目录，则视作选择它下面一级子 RJ 文件夹。若 RJ 文件夹为空，则将过滤后的该 RJ 资源直接下载进这个文件夹。

第一版只支持本地库存。远程群晖库存需要远程递归扫描、远程目标上传和冲突处理，先不混进本地实现。

## 业务流程

1. 前端入口：
   - `Library.vue` 批量工具栏新增“补全文件夹”按钮。
   - `LibraryRowContextMenu.vue` 单行/批量右键菜单新增“补全文件夹”。
   - 仅本地、可写、目录行启用；远程库和文件行禁用。
   - 点击后启动后台预览任务，不直接创建下载任务。

2. 后端预览：
   - 接收 `library_id` 和 `selected_paths`。
   - 默认走 `TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW` 后台任务；任务进入任务中心，`task_domain="asmr_sync"`，`source_action="folder_completion"`。
   - 任务进度通过现有任务中心 SSE 广播；前端弹窗和后台小窗共用同一个 job 状态，轮询只做兜底。
   - 校验库存存在、类型为本地、路径都在 `browse_root_path` 内。
   - 对每个选中目录：
     - 如果目录自身可识别 RJ，作为 RJ 目录。
     - 如果目录自身不可识别 RJ，扫描一级子目录，把可识别 RJ 的子目录作为目标；该目录按“社团目录”处理。
   - 对目标去重，避免同一个 RJ 文件夹被重复提交。
   - 拉取 ASMR.one `work_info + track_list`。
   - 将 ASMR.one track 扁平化为资源列表。
   - 用 `config.filter.rules` 复用 `asmr_download_service.filter_files()` 过滤远端文件表。
   - 扫描本地目录资源，复用 `ASMRResourceService.scan_local_resources()`。
   - 复用 `_match_remote_with_local()` 做远端资源与本地资源匹配。
   - 输出可下载项、跳过项、缺失列表、过滤数量、预计大小、默认勾选状态。

3. 用户确认：
   - 前端弹出预览确认弹窗。
   - 默认勾选所有“有缺失文件”的 RJ。
   - 展示每个 RJ：目标目录、ASMR.one 实际 RJ、远端总数、过滤后数量、已存在数、缺失数、预计下载大小、跳过原因。
   - 确认后调用启动接口。

4. 后端启动：
   - 接收 preview 产出的确认项，不重新信任前端路径，重新校验 `library_id/path/rjcode/session_id/selected_resources`。
   - 为每个 RJ 创建 `TaskType.ASMR_SYNC_DOWNLOAD`。
   - 任务元数据：
     - `download_mode: "enhanced"`
     - `source_page: "library"`
     - `source_action: "folder_completion"`
     - `source_label: "音声补全 / 补全文件夹"`
     - `task_domain: "asmr_sync"`，任务中心先归入 ASMR 同步，用 `source_action=folder_completion` 区分音声补全动作。
     - `selected_resources` 为缺失资源。
     - `download_base_path` 指向临时下载目录。
     - `upload_options.enabled=true`
     - `upload_options.mode="local"`
     - `upload_options.target_path=<目标 RJ 文件夹>`
     - `postprocess_options.enabled=false`
   - 下载成功后通过现有 `_upload_to_local()` 按资源 `relative_path` 写入目标 RJ 文件夹。
   - 任务完成后刷新库存统计并通知库存索引 self mutation。

## 后端拆分

新增服务：`backend/app/core/library_folder_completion_service.py`

核心方法：

- `resolve_targets(library_id, selected_paths)`
  - 专注路径解析、社团目录展开、RJ 提取、去重。
  - 不触网。
  - 返回 `FolderCompletionTarget[]`。

- `build_preview(library_id, selected_paths)`
  - 控制并发拉 ASMR.one。
  - 生成 session 和可下载资源。
  - 返回前端预览模型。

- `start_downloads(library_id, items)`
  - 校验 preview 项。
  - 创建增强下载任务。
  - 返回 task 列表。

- `_apply_extract_filter_rules(remote_resources)`
  - 将资源转换为 `asmr_download_service.filter_files()` 需要的 `{title,path,type,size}` 形状。
  - 过滤后映射回原始资源。
  - 记录 `filtered_out_count` 和过滤掉的相对路径。

- `_is_empty_rj_folder(local_resources)`
  - 本地资源为空时标记为 full download。
  - 注意忽略 `subtitles`、缓存目录等现有 `scan_local_resources()` 已跳过的目录。

## API 设计

新增请求模型：

```py
class LibraryFolderCompletionPreviewRequest(BaseModel):
    library_id: str
    selected_paths: list[str]

class LibraryFolderCompletionStartRequest(BaseModel):
    library_id: str
    items: list[dict]
```

新增接口：

- `POST /api/library/folder-completion/preview`
- `POST /api/library/folder-completion/preview/start`
- `GET /api/library/folder-completion/preview/jobs/{job_id}`
- `POST /api/library/folder-completion/start`

预览响应结构：

```json
{
  "success": true,
  "library_id": "...",
  "summary": {
    "target_count": 12,
    "downloadable_count": 8,
    "skipped_count": 4,
    "missing_file_count": 91,
    "estimated_bytes": 123456
  },
  "items": [
    {
      "key": "RJ010101:/path/RJ010101",
      "rjcode": "RJ010101",
      "actual_rjcode": "RJ010101",
      "folder_path": "...",
      "folder_name": "RJ010101 xxx",
      "work_title": "...",
      "mode": "missing_only",
      "remote_total": 30,
      "filtered_total": 24,
      "matched_total": 20,
      "missing_total": 4,
      "estimated_bytes": 1234,
      "session_id": "...",
      "selected_resources": []
    }
  ],
  "skipped": [
    {
      "path": "...",
      "reason": "未识别到 RJ / ASMR.one 无资源 / 过滤后无可下载文件 / 没有缺失文件"
    }
  ]
}
```

## 前端设计

新增组件：`frontend/src/components/library/LibraryFolderCompletionDialog.vue`

职责：

- 打开时启动或恢复后台 preview job。
- loading 遮罩只覆盖弹窗主体。
- 展示统计栏：可补全 RJ、缺失文件、预计大小、跳过数量。
- 列表支持勾选 RJ；默认勾选 `missing_total > 0` 的项。
- 每行展示目标目录、RJ、实际 ASMR.one RJ、缺失数量、过滤数量。
- 确认按钮用 `stateful-button.vue`。
- 暗色样式放组件 scoped + `html.kikoerumanager-dark`。
- 移动端用 `mobile-full-dialog`。
- 弹窗关闭后 preview job 继续在后台执行；库存页显示 `BackgroundFloatingCard` 小窗，badge 为“音声补全”。
- 小窗支持恢复预览弹窗；任务完成或失败后允许收起。

`Library.vue` 增加：

- `selectedFolderCompletionRows` computed。
- `folderCompletionDialogState`。
- `folderCompletionPreviewJob`。
- `canCompleteFolderRow(row)`。
- `openFolderCompletionDialog(rows)`。
- `handleFolderCompletionPreviewStarted(job)`。
- `handleFolderCompletionPreviewUpdated(job)`。
- `handleFolderCompletionBackgroundCardAction(action)`。
- 右键 action 分发：`folder_completion`。
- 批量按钮与菜单禁用态。

`frontend/src/api/index.js` 增加：

- `libraryApi.previewFolderCompletion(payload)`
- `libraryApi.startFolderCompletionPreview(payload)`
- `libraryApi.getFolderCompletionPreviewJob(jobId)`
- `libraryApi.startFolderCompletion(payload)`

## 性能瓶颈与处理

1. ASMR.one 请求瓶颈：
   - 多 RJ 批量时不能全并发。
   - 后端预览用 `asyncio.Semaphore(4)` 起步。
   - 同一个 RJ 去重，只拉一次。
   - preview 内缓存本批次 `work_info/track_list`，避免社团目录里重复 RJ 重拉。

2. 本地扫描瓶颈：
   - 只扫描目标 RJ 文件夹，不扫整个社团树。
   - 社团目录只展开一级子目录，禁止递归全树识别 RJ。
   - `scan_local_resources()` 对单个 RJ 目录执行，目录很多时放 `asyncio.to_thread`。
   - 大批量预览限制一次最多 100 个 RJ，超出返回 400，避免一次点整个库存根拖死 UI。

3. 文件匹配瓶颈：
   - 现有 `_match_remote_with_local()` 是远端 × 本地的双循环。
   - 第一版复用；但预览目标多、单目录文件多时要避免巨量对比。
   - 后续优化点：把 `_match_remote_with_local()` 改为按资源类型、`normalized_name`、track number 建索引匹配。

4. 过滤规则瓶颈：
   - 过滤只对远端资源表执行，不对本地文件做删除。
   - 复用现有 `filter_files()`，保证与 ASMR 同步/解压口径一致。
   - 无效正则按现有逻辑记录日志，不中断整个预览。

5. 任务创建瓶颈：
   - 一个 RJ 一个下载任务，复用现有任务并发控制。
   - `enhanced_max_parallel_sessions` 控制整体并发。
   - 单任务内部仍由 `enhanced_per_session_concurrency` 控制文件下载并发。
   - 批量创建后不等待下载完成，前端只提示任务已进入队列。

6. 磁盘与覆盖风险：
   - 下载先落临时目录，再通过 `_upload_to_local()` 写入目标 RJ 文件夹。
   - 只下载缺失资源，避免覆盖已有文件。
   - 如果目标相对路径已存在，下载任务侧应复用/跳过已有文件，不强覆盖。
   - 路径必须 sanitize，禁止 `..`、绝对路径和 Windows 非法字符穿透。

7. UI 响应：
   - preview 可能慢，弹窗显示分阶段状态。
   - 预览走后台 job，用户关闭弹窗后由后台小窗继续展示进度。
   - 任务中心 SSE 负责实时刷新任务中心；库存页监听同一事件并刷新当前 preview job，小窗再用低频轮询兜底。
   - 同步 `POST /preview` 仅作为兼容接口保留，前端默认使用 `POST /preview/start`。

## 边界规则

- 远程库禁用。
- 文件行禁用。
- 当前库存只读禁用。
- 选中目录自身有 RJ 时，不展开子目录。
- 选中目录自身无 RJ 时，只展开一级子目录。
- 同一路径重复选择只处理一次。
- 同 RJ 不同路径允许分别处理，因为目标文件夹不同。
- ASMR.one 实际命中翻译版时，下载 `actual_rjcode` 的资源，但任务目标仍写入用户选中的原 RJ 文件夹。
- “没有缺失文件”不创建任务，预览显示为 skipped 或 up_to_date。
- 空目录下载全量过滤后资源。

## 验证

后端：

- `py_compile`：
  - `backend/app/core/library_folder_completion_service.py`
  - `backend/app/api/routes.py`
  - touched core files

- 单元测试建议新增 `backend/tests/test_library_folder_completion_service.py`：
  - RJ 目录解析。
  - 社团目录一级展开。
  - 路径越界拒绝。
  - ASMR.one 无命中跳过。
  - 过滤后文件不计入缺失。
  - 空 RJ 文件夹 full download。
  - 非空 RJ 文件夹 missing only。
  - 批量去重与限制。

前端：

- `frontend` 下跑 `npm run build`。
- 手工检查：
  - 单行右键 RJ 文件夹。
  - 批量选择多个 RJ 文件夹。
  - 选择社团目录。
  - 远程库禁用。
  - 暗黑模式弹窗。
  - 移动端弹窗。

## 明确不做

- 第一版不支持群晖远程库存。
- 第一版不新增任务中心 domain，先归入 ASMR 同步并用 `source_action=folder_completion` 区分。
- 第一版不做自动删除本地多余文件，只补缺失。
