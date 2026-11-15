# MEGA 下载接入调研与实施方案

### MEGA API 错误说明（2026-11-10）

依据 [MEGA SDK 的 error 枚举](https://github.com/meganz/sdk/blob/master/include/mega/types.h)，
`backend/app/core/mega_errors.py` 集中定义全部 `-1` 至 `-30` API 错误，文件信息与文件夹节点请求共用。
错误显示保留中文含义、官方符号和原始数字，例如：
`MEGA：资源已被 MEGA 管理封锁，请更换有效分享；接口未提供具体封锁原因（API_EBLOCKED，错误码 -16）`。

重点区分：`-9` 资源不存在、`-14` 加解密错误、`-15` MEGA 会话无效、`-16` 管理封锁、
`-17` 配额超限、`-18` 暂时不可用、`-19` 连接过多、`-24` 剩余配额不足、`-29` 超存储配额付费限制。
`-17` 不直接断言是下载流量耗尽；`-16` 不猜测投诉或封禁原因。
未知负数保留原始错误码，非错误码的畸形响应明确显示格式异常，不输出响应体或分享密钥。
该映射只改善错误说明，不新增自动重试；HTTP 状态、网络异常和 MEGAcmd 进程退出码保持独立语义。

### 下载任务控制身份

MEGA 等 HTTP 下载任务即使携带 `session_id`，也不是 ASMR 增强下载会话。
工作台通过共享来源注册表 `isHttpDownloadTask` 判断传输类型，重试、暂停、恢复走 HTTP 任务接口，
取消及失败关闭按真实引擎任务 ID 清理全部分卷；不能仅凭 `session_id` 调用增强会话接口。
链接库 `link_sheet` 与 YAAS `imoutoheaven` 使用同一识别规则，避免合并卡片丢失类型字段后误报“会话不存在”。

## 结论

当前并发规则（2026-11-10）：MEGA 统一读取设置页 HTTP 下载的
`http_downloader.max_concurrent_downloads`，同批文件并行调度、跨任务共用并发上限。
没有 MEGA 专用并发配置或整文件互斥锁；修改上限后，等待中的下载按最新值领取槽位，
降低上限不打断已开始的传输。共享代理配置与提交命令只持有短锁，传输轮询、暂停、取消按各自标签独立执行。
文件夹下载也占用上述槽位，文件分片并发读取 `split` 和 `max_connection_per_server` 的较小值。
工作台继续汇总各文件的已下载字节、活动文件数和速度，不新增独立统计配置。
下文为初始接入调研，涉及并发的旧方案以本节为准。

第一版推荐接入官方 `MEGAcmd`，只覆盖 MEGA 公开分享链接下载：

- 支持 `mega.nz/file`、`mega.nz/folder`、旧格式 `#!` / `#F!` 链接。
- 支持带密钥的公开链接；带密码分享先按原始链接交给 `MEGAcmd`，不在系统内保存 MEGA 账号或密码。
- 不把 MEGA 链接交给 aria2。MEGA 链接不是稳定 HTTP 直链，文件密钥、目录树、解密和限额都在 MEGA 协议层，强行用 aria2 会丢失协议语义和错误信息。

系统接入方式：在现有 HTTP 外链下载链路里新增 `mega` 平台，仿照 Google Drive / Transfer.it 走专用下载分支，最终仍复用任务中心、下载工作台、操作历史和通知模板的 `download_files` 语义。

## 工具对比

### MEGAcmd（主方案）

- 官方维护，跨 Windows / Linux / macOS。
- 命令行能力完整，`mega-get <url> <target_dir>` 可以处理公开文件和公开文件夹。
- 适合本项目的桌面化部署：用户在宿主机安装 MEGAcmd，系统配置 `mega-get` 路径即可。
- 目录分享可以由 CLI 保留目录结构，后端只需要在下载结束后扫描落地目录并回填文件列表。

主要风险：

- 进度输出不是稳定 API，需要用“解析 stdout/stderr + 扫描落地文件大小”组合方式追踪。
- Docker 镜像内置 MEGAcmd 会增加镜像体积和包源复杂度，第一版不建议内置。
- 代理行为主要取决于 MEGAcmd / 系统网络设置，不应承诺完全复用 aria2 的代理参数。

### rclone mega（备选，不做第一版主路径）

- 更适合账号 remote、同步、挂载等长期管理场景。
- 公开链接下载不是它最自然的入口，接入后还要维护 remote 配置、账号会话和登录状态。
- MEGA 对频繁登录/命令有风控风险，第一版公开链接下载没必要把账号体系拉进来。

适合后续场景：用户明确需要“浏览 MEGA 账号云盘并选择文件下载”时，再设计账号配置和 remote 管理。

### megatools（轻量 fallback，不做默认）

- `megatools dl` 可以下载公开链接，依赖轻，概念简单。
- 维护活跃度、Windows 体验、目录分享和错误语义不如官方 MEGAcmd。
- 可以作为后续 fallback 下载模式，但第一版不作为默认方案。

## 接入边界

第一版只做：

- MEGA 公开文件链接下载。
- MEGA 公开文件夹链接下载。
- 任务中心展示下载进度、成功、失败、取消。
- 下载工作台预览时识别平台和目标目录。
- 操作历史、通知模板继续消费 `download_files`。

第一版不做：

- MEGA 账号登录。
- MEGA 账号空间浏览。
- 2FA、session 管理、配额缓存。
- MEGA 内部文件选择器。
- Docker 镜像内置 MEGAcmd。
- 用 aria2 下载 MEGA 文件。

## 后端实施方案

### 配置

在 `HttpDownloaderConfig` 增加：

```python
mega_enabled: bool = False
mega_cmd_path: str = "mega-get"
mega_download_mode: str = "megacmd"
```

配置语义：

- `mega_enabled`：是否启用 MEGA 链接解析和下载。
- `mega_cmd_path`：`mega-get` 可执行文件路径，Windows 可配置完整路径。
- `mega_download_mode`：预留下载实现，目前只接受 `megacmd`。
- 并发复用 `http_downloader.max_concurrent_downloads`，不增加 `mega_max_parallel`。

### 平台识别

在 `http_download_service.py` 增加：

- `_MEGA_HOST_HINTS = {"mega.nz", "www.mega.nz", "mega.co.nz", "www.mega.co.nz"}`
- `HTTP_DOWNLOAD_PLATFORM_LABELS["mega"] = "MEGA"`
- `normalize_http_download_platform()` 支持 `mega`、`mega.nz`、`mega.co.nz`
- `_provider_source()` 识别 MEGA URL 返回 `mega`

MEGA 链接仍走现有 URL 安全校验：

- 默认拒绝内网 / localhost / link-local / metadata 地址。
- `allow_private_network` 不应影响 `mega.nz` 正常下载，只保留现有全局行为。
- 日志、API 响应、任务元数据必须使用 `mask_http_download_url()`，避免泄露 key/password。

### 预览

在 `preview_urls()` 中新增 MEGA 分支：

- 未启用 `mega_enabled` 时返回失败项：`MEGA 下载未启用`。
- URL host 命中 MEGA 时生成 preview item：
  - `source: "mega"`
  - `filename`: 能从链接或用户输入推断则使用，否则用 `mega-download`
  - `masked_url`
  - `target_dir`
  - `final_path`
  - `relative_path`
  - `ok: True`
- 不在预览阶段强行调用 `mega-get`，避免预览造成实际下载或登录副作用。

### 下载执行

在 `start_download_task()` 中新增 `mega_items`：

- `google_drive_items`：继续走现有 Google Drive 专用下载。
- `transferit_items`：继续走现有 Transfer.it 专用下载。
- `mega_items`：新增 MEGA 专用下载。
- `aria2_items`：排除 `google_drive`、`transferit`、`mega`。

新增 `_download_mega_item(item, task=None, progress_callback=None)`：

- 用参数数组启动进程，不通过 shell：
  - `[mega_cmd_path, item["url"], item["target_dir"]]`
- Windows 下设置 `CREATE_NO_WINDOW`。
- stdout / stderr 异步读取，解析常见百分比输出；解析不到时定期扫描目标目录已写入大小。
- 每 1 秒左右刷新当前 row：
  - `status: "downloading"`
  - `downloaded`
  - `total` 未知时保持 `0`
  - `progress` 未知时保持小于 `99`
  - `speed_bytes_per_sec`
- 退出码为 `0` 后扫描目标目录：
  - 单文件链接：回填落地文件。
  - 文件夹链接：把目录下实际文件展开为多个 `download_files` row。
- 非 `0` 退出码写失败：
  - `status: "failed"`
  - `failure_reason`: 脱敏后的 stderr / stdout 摘要。

取消逻辑：

- 任务取消时终止 MEGAcmd 子进程。
- 先 `terminate()`，超时后 `kill()`。
- 不主动删除已写入文件，保持和现有 `cleanup_mode: files_only` 语义一致。

### download_files 字段

MEGA 初始 row：

```json
{
  "gid": "mega:<sha1(url)>",
  "name": "mega-download",
  "relative_path": "mega-download",
  "local_path": "<target>",
  "url": "<masked_url>",
  "original_url": "<raw_url>",
  "source": "mega",
  "status": "pending",
  "progress": 0,
  "downloaded": 0,
  "total": 0,
  "size": 0
}
```

下载完成后：

- 如果只落地一个文件，更新原 row 为 completed。
- 如果落地多个文件，保留一个目录汇总 row 或替换为实际文件 row，优先选择“实际文件 row”，因为任务中心、通知模板、历史记录已经以文件列表为核心。
- `final_output_path` 仍为 HTTP 下载根目录。

### 健康检查

`health()` 增加 MEGA 检查结果：

- `mega.enabled`
- `mega.cmd_path`
- `mega.available`
- `mega.version`
- `mega.message`

检查命令优先：

- `mega-version`
- 如果不可用，再尝试 `mega-get --version` 或 `mega-get --help`

未安装时只影响 MEGA 下载，不影响 HTTP / Gofile / Google Drive / PikPak。

## 前端实施方案

### 设置页

在 `HttpDownloadSettingsPanel.vue` 增加 MEGA 设置区块：

- `SettingsToggleRow`：启用 MEGA 下载。
- 输入框：`mega_cmd_path`，placeholder 为 `mega-get`。
- 数字步进：`mega_max_parallel`，范围 `1-4`，默认 `1`。
- 健康检查展示：
  - 已安装：显示版本。
  - 未安装：提示配置 `mega-get` 路径或安装官方 MEGAcmd。

文案重点：

- MEGA 下载走官方 MEGAcmd，不走 aria2。
- 代理以 MEGAcmd / 系统网络为准。
- 第一版只支持公开分享链接，不支持账号空间浏览。

### 平台元数据

在 `frontend/src/components/common/httpDownloadPlatformMeta.js` 增加：

- `mega` key
- label：`MEGA`
- title：`MEGA 下载`
- aliases：`mega`、`mega.nz`、`mega.co.nz`

图标：

- 优先新增本地资源 `frontend/src/assets/platforms/mega.*`。
- 如果没有合适资源，先用 lucide `Cloud` 或现有平台图标组件兜底，不使用外部热链。

### 设置草稿

在 `useSettingsDraft.js` 的 `defaultConfig.http_downloader` 增加：

- `mega_enabled: false`
- `mega_cmd_path: "mega-get"`
- `mega_download_mode: "megacmd"`
- `mega_max_parallel: 1`

保存配置时不需要额外脱敏，因为第一版不保存 MEGA 账号密码。

## 任务中心、历史和通知

不新增任务类型，继续使用 `TaskType.HTTP_DOWNLOAD`。

任务 metadata：

- `platforms` 包含 `mega`
- `platform_label` 为 `MEGA`
- `source_modes` 包含 `mega`
- `download_files[].source` 为 `mega`

任务状态：

- 全部成功：`completed`
- 部分成功：`partial_failed`
- 全部失败：走现有失败语义
- 取消：走现有取消语义

操作历史：

- 复用 `http_download_platforms_from_metadata()` 和 `http_download_platforms_label()`。
- 分类标题显示 `MEGA 下载`。
- 文件树继续由 `download_files` 生成。

通知模板：

- 不新增变量。
- 继续使用 `download_files` / `file_tree`。

## 测试计划

### 后端单测

覆盖平台识别：

- `https://mega.nz/file/...`
- `https://mega.nz/folder/...`
- `https://mega.co.nz/#!...`
- `https://mega.co.nz/#F!...`

覆盖链接脱敏：

- API 响应不暴露 MEGA key/password。
- 任务 `source_items`、`download_files.url`、失败原因都不泄露完整原始链接。

覆盖下载执行：

- mock `mega-get` 成功退出。
- mock `mega-get` 非 `0` 退出。
- mock 进程输出百分比。
- mock 下载目录落地多个文件。
- mock 任务取消时进程被终止。
- 未安装 `mega-get` 时返回明确业务错误。

最低验证命令：

```powershell
.\.venv\Scripts\python.exe -m py_compile backend/app/config/settings.py backend/app/core/http_download_service.py backend/app/api/routes.py
```

### 前端验证

最低验证命令：

```powershell
cd frontend
npm run build
```

重点检查：

- 设置页默认配置可正常加载。
- MEGA 平台标签显示在下载工作台、任务中心、操作历史。
- 暗色模式下设置区块样式正常。
- 移动端设置页不溢出。

### 手工验收

- 安装官方 MEGAcmd 后，配置 `mega-get` 路径。
- 粘贴公开文件链接，能下载到 `http_downloader.download_root`。
- 粘贴公开文件夹链接，能保留目录结构。
- 下载中取消任务，任务中心状态正确。
- 未安装 MEGAcmd 时，健康检查和下载失败文案明确。
- MEGA 链接中的 key/password 不出现在日志、任务列表、历史详情和通知预览中。

## 下载残留清理（2026-11-11）

- MEGAcmd 文件校验并发布成功后，删除当前文件暂存区，并尝试删除空的任务目录及外层 `.mega-staging`。其他任务仍在使用的目录不受影响。
- 下载失败时保留暂存内容供重试；关闭任务并请求清理时，同时处理 `.aria2`、`.part` 和下载目标同层 `.mega-staging/<task-id>`，不删除公共下载根或其他任务暂存区。
- 外层 `.mega-staging` 即使为空，也会阻止归档器清理源目录及会话、RJ 父目录。排查旧残留应先确认目录树内有无文件，不得把 RJ 目录或下载器 `.aria2-rpc` 整体视为垃圾。

## 后续扩展

如果后续要支持 MEGA 账号空间浏览，需要单独设计：

- `MegaAccountConfig`
- session / config 目录隔离
- 账号密码或 token 脱敏
- 2FA 输入流程
- 账号配额缓存
- 云端目录浏览 API
- 多账号下载路由

这部分不要混进第一版公开链接下载，否则会把外链下载能力拖成完整网盘客户端。

## 参考

- 官方 MEGAcmd：<https://github.com/meganz/MEGAcmd>
- rclone MEGA backend：<https://rclone.org/mega/>
- megatools 文档：<https://megatools.megous.com/man/megatools.html>
