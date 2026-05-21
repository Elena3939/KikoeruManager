# 改进的查重功能 - 快速开始指南

## 概述

本指南介绍如何使用改进后的查重功能，该功能支持检测关联作品（不同语言版本）。

## 新功能

### 1. 查询关联作品

**API 端点:** `GET /api/linked-works/{rjcode}`

**示例:**
```bash
curl "http://localhost:8000/api/linked-works/RJ01234567?include_full_linkage=true&cue_languages=CHI_HANS,CHI_HANT,ENG"
```

**返回示例:**
```json
{
  "rjcode": "RJ01234567",
  "translation_info": {
    "is_original": true,
    "is_parent": false,
    "is_child": false,
    "lang": "JPN"
  },
  "linked_works": {
    "RJ01234567": {
      "workno": "RJ01234567",
      "work_type": "original",
      "lang": "JPN",
      "title": "原作品标题"
    },
    "RJ01234568": {
      "workno": "RJ01234568",
      "work_type": "parent",
      "lang": "CHI_HANS",
      "title": "中文版标题"
    }
  },
  "total_count": 2
}
```

### 2. 检查库中关联作品

**API 端点:** `GET /api/linked-works/{rjcode}/check-library`

**示例:**
```bash
curl "http://localhost:8000/api/linked-works/RJ01234567/check-library"
```

**返回示例:**
```json
{
  "rjcode": "RJ01234567",
  "is_in_library": true,
  "library_works": [
    {
      "rjcode": "RJ01234568",
      "work_type": "parent",
      "lang": "CHI_HANS",
      "work_name": "中文版标题",
      "path": "E:/Library/RJ012xxxx/RJ01234568 中文版标题",
      "size": 123456789,
      "file_count": 15
    }
  ],
  "total_linked": 2,
  "found_in_library": 1
}
```

### 3. 改进的查重检查

**API 端点:** `POST /api/conflicts/enhanced-check`

**示例:**
```bash
curl -X POST "http://localhost:8000/api/conflicts/enhanced-check" \
  -H "Content-Type: application/json" \
  -d '{
    "rjcode": "RJ01234567",
    "check_linked_works": true,
    "cue_languages": ["CHI_HANS", "CHI_HANT", "ENG"]
  }'
```

**返回示例 (发现关联作品):**
```json
{
  "is_duplicate": true,
  "conflict_type": "LINKED_WORK_TRANSLATION",
  "direct_duplicate": null,
  "linked_works_found": [
    {
      "rjcode": "RJ01234568",
      "work_type": "parent",
      "lang": "CHI_HANS",
      "path": "E:/Library/...",
      "size": 123456789,
      "work_name": "中文版标题"
    }
  ],
  "related_rjcodes": ["RJ01234567", "RJ01234568"],
  "analysis_info": {
    "current_work": {
      "rjcode": "RJ01234567",
      "work_type": "original",
      "lang": "JPN"
    },
    "has_original": true,
    "has_translation": true,
    "library_summary": [...]
  },
  "resolution_options": [
    {
      "action": "KEEP_BOTH",
      "label": "保留两者",
      "description": "原作品和翻译版本是不同作品，建议保留",
      "recommend": true
    },
    {
      "action": "KEEP_NEW",
      "label": "保留新版（原作品）",
      "description": "用新版原作品替换翻译版本（不推荐）"
    }
  ]
}
```

## Kikoeru 搜索配置

### 创建配置

**API 端点:** `POST /api/kikoeru-configs`

**示例:**
```bash
curl -X POST "http://localhost:8000/api/kikoeru-configs" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "家庭Kikoeru",
    "search_url_template": "http://192.168.1.100:8080/api/search?keyword=%s",
    "show_url_template": "http://192.168.1.100:8080/works?keyword=%s",
    "enabled": true
  }'
```

### 获取配置列表

**API 端点:** `GET /api/kikoeru-configs`

### 更新配置

**API 端点:** `PUT /api/kikoeru-configs/{config_id}`

### 删除配置

**API 端点:** `DELETE /api/kikoeru-configs/{config_id}`

## 前端集成建议

### 1. 冲突页面增强

在 `Conflicts.vue` 中添加关联作品显示：

```vue
<template>
  <div v-if="conflict.linked_works_info && conflict.linked_works_info.length > 0">
    <h4>发现关联作品:</h4>
    <div v-for="work in conflict.linked_works_info" :key="work.rjcode" class="linked-work">
      <span class="work-type">{{ work.work_type }}</span>
      <span class="work-lang">{{ work.lang }}</span>
      <span class="work-name">{{ work.work_name }}</span>
      <span class="work-path">{{ work.path }}</span>
    </div>
  </div>
</template>
```

### 2. 关联作品树形图

为复杂的关联关系创建可视化：

```vue
<template>
  <div class="linkage-tree">
    <div class="original-work">
      原作品: {{ originalWork.rjcode }}
    </div>
    <div class="translations">
      <div v-for="trans in translations" :key="trans.rjcode" class="translation">
        {{ trans.lang }}: {{ trans.rjcode }}
      </div>
    </div>
  </div>
</template>
```

### 3. 添加"检查关联作品"按钮

在入库流程中添加手动检查按钮：

```vue
<template>
  <div class="duplicate-check-actions">
    <button @click="checkDirectDuplicate">检查直接重复</button>
    <button @click="checkLinkedWorks">检查关联作品</button>
  </div>
</template>

<script>
async function checkLinkedWorks() {
  const response = await fetch(`/api/linked-works/${this.rjcode}/check-library`);
  const data = await response.json();
  
  if (data.is_in_library) {
    this.showLinkedWorksDialog(data.library_works);
  }
}
</script>
```

## 常见使用场景

### 场景 1: 处理翻译版本

**问题:** 已有原作品 RJ01234567，现在要添加中文版 RJ01234568

**解决:**
1. 系统检测到这是关联作品
2. 显示冲突类型: `LINKED_WORK_ORIGINAL`
3. 推荐操作: "保留两者"
4. 两个版本都保留在库中

### 场景 2: 发现重复 RJ 号

**问题:** 库中已有 RJ01234567，又添加了同 RJ 号的新版本

**解决:**
1. 系统检测到直接重复
2. 显示冲突类型: `DUPLICATE`
3. 提供选项:
   - 保留新版（删除旧版）
   - 保留旧版（删除新版）
   - 合并（保留两个，新版加编号）
   - 跳过（删除新版）

### 场景 3: 批量检查

**问题:** 想检查一批作品是否已有关联版本在库中

**解决:**
```javascript
async function batchCheckLinkedWorks(rjcodes) {
  const results = await Promise.all(
    rjcodes.map(rjcode => 
      fetch(`/api/linked-works/${rjcode}/check-library`).then(r => r.json())
    )
  );
  
  return results.filter(r => r.is_in_library);
}
```

## 注意事项

1. **API 缓存**: DLsite API 响应缓存 24 小时，如需刷新请重启服务
2. **网络依赖**: 关联作品查询需要访问 DLsite API，确保网络通畅
3. **性能考虑**: 完整关联链查询可能较慢，建议在后台执行
4. **语言代码**: 使用标准语言代码（CHI_HANS, CHI_HANT, ENG 等）

## 故障排除

### 问题: API 返回 500 错误

**可能原因:**
- DLsite API 不可访问
- RJ 号格式错误

**解决:**
- 检查网络连接
- 确认 RJ 号格式正确（RJ + 6-8位数字）

### 问题: 关联作品查询为空

**可能原因:**
- 该作品没有翻译版本
- API 响应被缓存

**解决:**
- 确认 DLsite 上该作品确实有翻译版本
- 等待 24 小时缓存过期或重启服务

### 问题: 库中作品检测不准确

**可能原因:**
- LibrarySnapshot 表未同步

**解决:**
- 执行库扫描以更新快照表

## 配置文件示例

```yaml
# config.yaml 中的 Kikoeru 配置（可选）
kikoeru_search:
  enabled: true
  configs:
    - name: "家庭Kikoeru"
      search_url: "http://192.168.1.100:8080/api/search?keyword=%s"
      show_url: "http://192.168.1.100:8080/works?keyword=%s"
      enabled: true
```

## 更新日志

### v1.5.43 - 智能伪装多卷分卷补全探测重构 + 任务取消崩溃 NameError 修复

- **后端**：重构伪装多卷（分卷压缩包后缀无法识别）探测，新增 `_detect_disguised_set_with_clean_target` 算法。解决 target 为干净主卷（如 `RJ01358521.zip`）但兄弟卷全是伪装（如 `.删除z02 / .删除z03`）时原算法无法拆解、直接跳过导致下游误报"无正确密码/压缩包损坏"的痛点，实现自动提取干净 target 并智能重构伪装兄弟卷的改名建议。
- **后端**：在 `task_engine` 的 generic dispatcher cancellation 处理中移除未定义的 `append_progress_log` 调用，避免用户主动取消或暂停正在进行 7zz 等子进程任务时抛出 NameError 毁掉 cancel 状态更新流程的问题。
- **测试**：在 `test_extract_service.py` 补充 23 个针对伪装判定、兄弟卷剥离、干净主卷伪装兄弟探测、魔数不可读兜底等核心边界的自动化测试，100% 通过。

### v1.3.0 - 解压并发按存储类型自适应 + 7z 多线程 + verify scandir 优化

- **后端**：`ExtractService._detect_storage_type` 跨平台探测 `temp_path` 所在物理盘（Windows 走 `Get-PhysicalDisk`，Linux 读 `/sys/dev/block/*/queue/rotational`），结果缓存到 class 级。`extract.max_concurrent_extractions` 默认 `0 = auto`：SSD → `min(processing.max_workers, 3)`，HDD / 未知 / 网络盘 → 1（机械盘并发寻道会让磁头在多个 GB 级文件之间疯狂寻道，实测单包从 12 分钟跌到 1.5 分钟）
- **后端**：4 个真正的 7z 解压命令统一加 `-mmt=on` 多线程，单包 LZMA2 / deflate 吃满多核（`extract.seven_zip_threads` 可调 "on"/"off"/数字）
- **后端**：`_verify_extraction` 改用一次 `os.scandir` 递归建表 + dict O(1) 查表，取代 per-file `os.path.exists` + `getsize`。几千文件的大包 verify 阶段从十几秒缩到 1 秒以内，少一轮 MFT 寻道
- **后端**：新增 `GET /api/system/storage-info`，返回 `temp_path / library_path / input_path` 的存储类型探测结果、auto 模式下实际会选的并发值、当前配置值
- **前端**：设置页「处理与解压」新增「解压并发数（7z 子进程）」下拉（自动 / 1 / 2 / 3 / 4），右侧绿色 SSD / 黄色 HDD chip 实时显示探测结果，下方 hint 动态解释当前生效值
- **新增脚本**：`scripts/add-defender-exclusions.ps1` 一键给 Windows Defender 添加 ASMR 工作目录和 7z/Python/KikoeruManager 进程排除项，解决 AV 实时扫描把 NVMe SSD 打到个位数 MB/s 的问题
- **前端**：侧栏 `NotificationBell` 铃铛外圈 48→60px、内层 Lottie 38→50px，铃铛在 logo 区视觉权重提高，避免被品牌名压扁
- **CI**：`.github/workflows/ghcr.yml` 去掉 master / main 分支触发，只在 `v*.*.*` tag 推送时才跑 image 构建 + Docker Hub README 同步

### v1.2.3 - Kikoeru 8 位 RJ 号 work_id 前导 0 修复（彻底解决关联作品漏检）

- **后端**：`_rjcode_to_id` 用 `int()` 把带前导 0 的 8 位 RJ 号（如 `RJ01337508`）抹成 `1337508`，导致 `/api/tracks/1337508` 永远 404，v1.2.2 加的 work_id 兜底名存实亡。新增 `_rjcode_to_work_id_str` 取 RJ 数字部分**字符串原样**（保留前导 0 = `01337508`），新增 `_build_tracks_url_str` 拼对应 URL（参考 VoiceLinks 油猴脚本 `getAsmrOneWorkId` 的实现）
- **后端**：`_probe_work_by_id`（兜底路径）和 `_hydrate_track_subtitle_state`（search 命中后的字幕统计路径）都改为优先使用字符串 work_id，彻底兼容 8 位带前导 0 的 RJ 号
- **后端**：`_parse_search_result` 增加候选 works 诊断日志（id / sourceWorkno / candidate_rjcodes 预览），定位"网页搜得到但 backend 报未命中"问题时能直接看 backend 拿到的 search 响应
- **修复用户痛点**：`RJ01304475` 关联作品 `RJ01337508` 在 kikoeru 上明明有，但解压入库 / 测试查重判定整条链路未命中

### v1.2.2 - Kikoeru 关联作品「明明有却查不到」修复

- **后端**：`KikoeruDuplicateService.check_duplicate` 在 `/api/search?keyword=RJxxxxxx` 未命中时，新增按 RJ→work_id 直接打 `/api/tracks/{id}` 的硬兜底（`_probe_work_by_id`）。某些 kikoeru 部署的 search 全文索引对带前缀 0 的新作 RJ 号 / 翻译版的 sourceWorkno 索引会漂移漏掉，但 work_id 路由是稳定的，HTTP 200 即代表 work 存在。修复用户痛点："RJ01304475 在 kikoeru 网页上能搜到，但解压入库预检判定整条链路未命中"
- 401 重登路径同样接 work_id 兜底
- 兜底命中时同步填好字幕统计字段（`subtitle_file_count` / `total_track_count` / `has_lyric_hint`），不影响后续字幕补配判断流程

### v1.2.1 - 字幕补配「卡 60s 但实际已导入」修复

- **后端**：`execute_pending_import` 主流程的源压缩包归档（可能跨卷搬 GB 文件）改为 `asyncio.create_task` fire-and-forget 后台执行，HTTP 立刻返回 `task.id` 给前端跳转工作台。修复用户痛点："实际后端已经导入成功了，但前端 60s 超时没打开工作台"
- **前端**：`executePendingImport` catch axios timeout 时自动重查 pending 列表 3 次（间隔 2/4/6s），若状态已 IMPORTED 自动 `openImportedTask` + 提示"已成功 + 后台归档中"，避免用户以为卡死重复点导入
- **前端**：侧边栏 logo 区布局调整：品牌名字号 20→16px + nowrap + ellipsis 兜底；铃铛尺寸 48→36px；gap 12→8px；铃铛与 KikoeruManager 不再重叠
- **前端**：`appVersion` 同步从硬编码 `'1.0.14'` 改为读 package.json 同步值

### v1.2.0 - 性能与稳定性大修

- 字幕工作台「应用配对」从串行 60+ HTTP 缩到 2-4 次 batch HTTP，群晖 Docker 上 30 对配对从 5-30 秒降到 0.5-1 秒
- 新增 `/api/library/browser/batch-rename` 批量接口，单事务完成多条 rename + 1 次索引同步 + 1 次缓存清理
- 字幕预检 / 工作台 stage 复制改 `ThreadPoolExecutor` 并发，30 个字幕复制速度提升 5-8 倍
- 嵌套小压缩包识别重写：默认走常规解压，仅"强证据 + 整词匹配 + 内容清一色字幕扩展名"才视为字幕包，修复命名不规范奖励包漏解压
- 新增 `fs_utils.move_path_efficient`：跨卷归档 / 分类用 8MB buffer 流式复制 + 实时进度回调，归档大文件不再卡 95%
- `_wait_file_stable` 重写：mtime 稳定判定 + PermissionError 累计软放行 + max_wait 缩到 1800s，修复群晖 NAS 上偶发"等 3600 秒"死锁
- 任务中心 `_build_all_items` 加分步 try/except + 顶层兜底，单条任务异常不再让任务中心 500
- 日志页 OOM 修复：highlightCache 长 cacheKey 不缓存、parse/highlight 上限缩小、`logLimit` 砍到 1000、切条数 / 离开页面主动清缓存
- 日志搜索全历史模式不再二次过滤 keyword，修复"X 总计 0 匹配"
- 字幕补配 API timeout 从 60s 加到 10 分钟，前端兜底 setTimeout 15 分钟避免按钮永远卡 loading

### v1.1.0 - 改进查重功能
- ✅ 关联作品检测
- ✅ 翻译版本识别
- ✅ 详细冲突分析
- ✅ Kikoeru 搜索配置
- ✅ 改进的 API 端点

## 技术支持

如有问题，请查看:
1. 后端日志: `data/app.log`
2. API 文档: `http://localhost:8000/docs`
3. 数据库: `data/cache.db`
