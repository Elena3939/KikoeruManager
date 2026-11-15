# DLsite 列表 DOM 解析与 A/B 验收

## 变更范围

2026-11-15，本地加入 `selectolax>=1.0.2,<2`，当前安装版本为 1.0.2。
`DLsiteApiService._extract_summaries_from_listing_html()` 使用 Lexbor 构造一次 DOM，
按原有模板优先级选择卡片，并直接读取作品号、图片、社团和分类节点。
去掉了每个 RJ 动态拼接的两条图片正则，避免大页反复编译及冲掉 `re` 缓存。
标题链接只在相应小节点中执行固定正则，保留原先的紧邻锚点优先级。

作品号全页扫描、音声分类规则、请求/代理/重试/缓存及线程调度未改变。
没有已知卡片模板时，保留原有 product_id 锚点切片支持。
此次没有修改详情页 `work_outline` 解析，也没有修改数据库。

裸日期仅从当前卡片文字读取。之前整段 HTML 搜索会命中汇率属性中的小数，
日期页最后一张卡片的正则还会将页尾日期带入作品。本次修正这些来源错误，
缺少可信日期时保留空值，继续由原来的元数据链处理。

## 测量方法

- Windows x64，Python 3.12.10，selectolax 1.0.2。
- A 组为变更前冻结的完整服务文件，B 组为当前服务；均调用实际业务方法。
- 3 次预热，21 轮，每轮每组执行 3 次，交错 A/B 与 B/A 顺序。
- 记录每轮平均单次耗时，统计中位数和 P95；结果转字典仅用于一致性比较，不计入耗时。
- `summary` 为摘要解析；`pipeline` 为实际 `_parse_listing_response_sync()` 完整同步链，
  包含摘要、全页作品号提取和 DLsite 页面判别。
- 同一批页面在内存中回放，排除网络请求、HTTP 解码、排队和数据库开销。
- 内存为相同导入和输入下三次独立进程的峰值工作集，包含 Lexbor 原生堆。

原始记录在本机 `data/selectolax-ab/final.json`，包含源码和页面 SHA-256。
基线源码 SHA-256：`553c56f9a43b3a34c05d890993877cb3ce58b028880898371f8ff7972099e1eb`。

## 实测结果

以下为完整同步解析链的单页中位数。

| 输入 | HTML 大小 | 摘要条目 | A 旧实现 | B DOM 实现 | A/B |
| --- | ---: | ---: | ---: | ---: | ---: |
| 历史 PC 列表 variant-0 | 696,548 B | 100 | 39.61 ms | 16.16 ms | 2.45 倍 |
| 历史列表 variant-1 | 455,317 B | 70 | 23.05 ms | 10.88 ms | 2.12 倍 |
| 历史列表 variant-2 | 383,368 B | 70 | 21.23 ms | 9.97 ms | 2.13 倍 |
| 当日抓取 RG55461 社团页 | 300,347 B | 50 | 16.38 ms | 7.81 ms | 2.10 倍 |
| 当日抓取 2026-11-14 发售日页 | 1,610,494 B | 267 | 149.31 ms | 40.94 ms | 3.65 倍 |
| 无已知列表卡片的单作品详情页 variant-3 | 71,304 B | 1 | 1.47 ms | 2.52 ms | 0.58 倍 |

只看摘要解析，五张列表页提升 2.59～4.83 倍。
最大日期页的完整链 P95：155.23 ms → 44.05 ms。
无列表卡片的兼容输入因 DOM 建树与片段解析多耗约 1.05 ms，未声称所有输入都提速。
这些是解析阶段数据，不能作为整个社团索引、网络抓取或页面加载的提速倍数。

独立进程峰值工作集中位数：A 44.79 MiB，B 56.08 MiB，增加约 11.30 MiB。
日期大页连续解析 200 次的补充检查记录在 `data/selectolax-ab/memory-stability.json`：
第 10 次峰值约 52.03 MiB，第 200 次约 52.57 MiB；这不是长期并发内存无泄漏证明。

## 正确性验收

六张真实 HTML 共 558 条摘要记录（跨页有重复作品）。

- 作品数量、返回顺序、全页作品号列表和站点判别一致。
- 除发售日修正外，标题、社团、封面、类别、格式、音声三态及判定原因均一致。
- 日期差异共 303 条记录、涉及 246 个不同 RJ；这是重复快照中的记录数，不能说成 303 部作品。
- 302 条旧日期来自卡片 HTML 属性数字，1 条来自当前卡片以外日期。
  其中 297 条旧值连日历日期都不合法，另 6 条格式合法但来源错误。
- 所有这些差异均为旧误判值改为空值，逐条核对数字来源后冻结精确差异清单。
  不把所有日期差异自动当作允许差异。
- `tools/benchmark-dlsite-html-parser.py` 同时比较全字段和人工复核的精确差异清单；
  未允许的字段、顺序、作品号或日期变化会退出码 1。

回归测试：49 passed，覆盖 DOM 边界、嵌套列表、邻作隔离、单引号、HTML 实体、懒加载封面、
日期来源、模板优先级、无作品输入、原有列表/日期页、翻译链及元数据可信度。
另一次扩大到特典数据库套件的探索运行有 111 passed、32 个 setup error；
错误均为 `--noconftest` 下缺少数据库 fixture，这部分未作数据库集成验收结论。

新测试在 `backend/tests/test_dlsite_html_parser.py`；本机 `.git/info/exclude` 忽略了
`backend/tests/`，该文件作为本地验收文件保留，未改变忽略规则、暂存或提交。

## 复现

在仓库根目录用 PowerShell 7 执行，使用已冻结的旧实现和同一批本地快照。

```pwsh
$samples = @(
  'data/run/circle-count-20261019/variant-0.html'
  'data/run/circle-count-20261019/variant-1.html'
  'data/run/circle-count-20261019/variant-2.html'
  'data/run/circle-count-20261019/variant-3.html'
  'data/selectolax-ab/live-maker.html'
  'data/selectolax-ab/live-date.html'
)
```

```pwsh
& backend/venv/Scripts/python.exe -X utf8 tools/benchmark-dlsite-html-parser.py `
  --baseline data/selectolax-ab/dlsite_service_before.py `
  --html @samples `
  --expected-differences data/selectolax-ab/expected-differences.json `
  --output data/selectolax-ab/recheck.json
```

无差异清单时仍可运行并生成报告，但存在差异时返回失败，要求先复核。
快照、旧源码和完整报告保存在被忽略的 `data/`，不随业务源码发布。

## 依赖与运行边界

本地已安装 Windows CPython 3.12 x64 wheel；已实际下载并确认 CPython 3.11 的
Linux manylinux2014 x86_64 和 aarch64 wheel，未在 Linux 容器里执行测试。
两个 Dockerfile 都从 `backend/requirements.txt` 安装依赖，不需要增加系统包或改 Dockerfile。
此次未提交、未重启开发服务、未发布生产；增加原生依赖后的生产发布需要完整镜像流程。
