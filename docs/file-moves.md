# 业务文件移动与宿主克隆

## 提交边界

业务移动统一调用 `app.core.fs_utils`。精确目标移动使用 `move_path_sync` / `move_path_efficient`，保留旧目标直到新内容就绪的替换使用 `move_path_replacing_sync`，自行控制发布的业务使用 `copy_path_exclusive_sync`。目录合并仍由业务层逐项处理冲突和库存索引。

普通移动先执行无覆盖原生重命名，只有 `EXDEV` 才准备跨挂载副本。权限、目标冲突、空间及路径错误直接报错。启用宿主加速后，执行器通过 Btrfs UUID 或文件系统身份决定克隆/流式复制；同文件系统克隆失败不能悄悄复制。符号链接不跟随，树内硬链接保留，拒绝设备、FIFO、socket。

跨挂载使用目标旁独占暂存、来源与成员校验、原子发布、清源顺序。每次清源前及逐项删除边界检查取消。异步调用必须使用 `run_file_operation_async` 或 `move_path_efficient`，取消等待真实线程结束。发布后的清源异常抛出 `MoveCleanupPending`，调用方不能回滚目标。

配置、下载断点、缓存及 `.part` 发布继续使用原子替换；远程 FileStation 保留远程 API。日志阶段为重命名、快速克隆、流式复制、校验、清理来源。克隆进度是逻辑字节，不代表磁盘吞吐；归档、上传原有 SHA-256 仍会读取全部内容。

## 默认配置

```yaml
file_move:
  host_enabled: false
  socket_path: /app/data/.host-file-mover/control.sock
  request_timeout_seconds: 30
  journal_path: ''
```

空 journal_path 使用持久化 data 下的 `file-moves`。桌面环境无需执行器；启用加速后离线或映射不符会保留来源并报错。

## 安装包与启用

先发布含客户端的完整应用镜像，再使用真实 `docker inspect`、运行 UID/GID 生成安装包。安装包自动同步所有可写 bind 业务挂载，不再只授权当前设置选中的路径；可选应用业务配置或路径清单用于补充挂载内的业务子目录。不要将完整含凭据配置收入发布包。配置、数据库、代码、系统目录和只读挂载不参与搬运；`/app/data` 仅授权上传与过滤恢复两个子目录。

```text
python tools/host-file-mover-install.py --inspect-json inspect.json --uid 0 --gid 0 --bundle bundle --host-python /bin/python3
```

生成安装包不会安装服务。`--host-python` 必须是已核实的宿主 Python 3.8+ 路径。宿主 root 显式安装：

```text
python3 tools/host-file-mover-install.py --install --bundle bundle --production
```

安装时重新读取真实 inspect、UID/GID、Python 版本，校验 SHA-256、映射和容器身份；启动 systemd 服务后从真实容器做 socket 探测。服务使用异常重启及开机启动，不新增 TCP 端口或业务挂载。安装失败恢复上个 current 链接和 unit；成功只保留三份版本。安装器不修改 host_enabled。

## 设置页与只读诊断

设置 → 文件移动加速可调整 `host_enabled`、`socket_path`、`request_timeout_seconds`、`journal_path`，使用页面顶部保存。当前配置、执行器在线和业务白名单就绪分别显示；草稿开关不会冒充实际启用状态。状态每 15 秒刷新，页面隐藏时暂停轮询。

`GET /api/system/file-move/status` 检查当前容器到宿主的真实连接，返回映射版本、容器身份、启动时间、全部已授权挂载与已配置业务根目录的并集及恢复记录摘要，不返回宿主绝对路径。`configured` 标记当前业务使用的目录；`ready` 校验这些必要目录，额外挂载不可用不会阻塞无关配置。`POST /api/system/file-move/probe` 接受已配置业务根目录或执行器已授权的挂载根目录，检查真实文件系统身份，不创建或移动文件；实际克隆能力仍以独立目录验收为准。

通过通用配置接口启用加速、修改加速参数或已启用时修改业务目录，必须通过执行器连通和映射检查。关闭加速不要求执行器在线。恢复目录存在记录时禁止改路径；摘要每次最多查看 500 条、读取 16 MiB，并限制扫描时间，不能把摘要当成自动恢复或删源依据。

已有任务不会中途切换搬运方式。不同文件系统仍使用流式复制；同文件系统的克隆异常明确失败并保留来源。首次升级此修复、容器重建或业务挂载变化后重新生成、安装映射包；已有挂载之间切换业务路径无需重装。网页不提供宿主任意命令执行或服务安装入口。

仅包含源码与静态资源的隔离联合发布，可使用 `deploy-production-local-build.ps1 -PreparedDirectory ... -ExpectedImage sha256:... -SourceRevision ...`。目录只能包含 `app/**/*.py` 和完整 `static/`；必须由生产镜像相同源码修订构建。工具核对精确镜像与源码标签，重新生成哈希清单，沿用任务空闲检查、备份、重启、健康验证和失败回滚。此模式不会收集工作区其余改动，不适用于依赖、入口、架构或镜像运行时变化。

完整镜像发布与宿主服务启用必须另行授权。发布前确认主机 Elena、生产容器、任务空闲、文件哈希和 API 健康，保留三份可追溯回滚版本。容器重建导致 ID 改变时必须重新生成映射包。当前没有自动跨应用/执行器/配置的一键回滚命令；发布工具需按对应清单恢复三者后再验证健康，不能只回退镜像并继续启用旧映射。

## 中断恢复

先停止相关业务任务，再在应用环境运行：

```text
python -m app.core.file_move_recovery status
python -m app.core.file_move_recovery resume --source /原始/来源
python -m app.core.file_move_recovery restart-preparing --source /原始/来源
```

`resume` 继续已暂存操作；已发布只核对身份并继续清源，不重新覆盖。`restart-preparing` 先确认执行器停止，再隔离归属可确认的残留，返回隔离路径；不会删除未知成员。来源变化或归属不明时保留现场。隔离目录经人工核对后再删除。延后归档另外保留租约/epoch、卷组与数据库发布记录；归档 owner.json 只允许同来源身份重建暂存，旧 epoch 残留须核对后处理。

## 验证入口

```text
python tools/check-file-move-coverage.py
python -m pytest backend/tests/file_moves --confcutdir=backend/tests/file_moves -q
python tools/verify-host-file-mover.py --modules /独立测试包/app/core --pairs-json pairs.json --data-host /真实/data/挂载源
```

AST 清单逐项登记原子提交等豁免，新增裸搬运入口会失败；这不替代调用链和取消语义审查。NAS 工具只创建独占测试目录，退出时精确清理，临时前台执行器不安装服务。pairs.json 每项提供 host_source、host_target、container_source、container_target；必须来自已核对 inspect，真实跨文件系统项可选宿主临时测试目录。

本地测试覆盖重命名、EXDEV、克隆选择与失败、硬链接、取消等待、并发目标、中断恢复、上传保源及归档暂存。Windows 无符号链接权限时该项跳过。需要 PostgreSQL 的归档租约、库存索引完整回归必须在独立测试库中执行；数据库 fixture 失败不能计为通过。NAS 验收报告与本地单元测试分别记录，不能将模拟克隆等同于真实 Btrfs 验收。

## 前期隔离验证记录（2026-10-25，正式安装前）

- Windows 工作区定向测试：93 通过、2 跳过（符号链接权限）；隔离已有改动后，独立提交树重新验证：89 通过、2 跳过。
- PostgreSQL 库存索引 mutation 测试未运行：本机测试数据库连接超时，fixture 初始化失败；不计入通过数量。
- NAS 主机 Elena，生产容器健康，应用版本 1.6.130，宿主 Python 3.8.12。仅在独占目录内启动临时前台执行器，未安装服务、未改应用配置、未部署。
- ANIME、ASMR 两组路径均通过实际 FICLONE、SHA-256、COW 修改隔离、目录事务、空文件、树内硬链接及符号链接测试；综合耗时分别约 0.715 秒和 0.689 秒，含校验，不能用作磁盘吞吐基准。
- ASMR 到宿主 /dev/shm 的真实跨文件系统流式复制，以及容器到宿主 Unix socket 来源鉴权和克隆通过；独占测试目录已清理。
- 未采集磁盘读写计数；完整镜像发布、systemd 正式安装以及应用/执行器/配置联动回滚演练仍须在正式发布前完成。

## 正式安装与设置页验收（2026-10-25）

- 用户授权后，在 Elena 为生产容器安装 `kikoerumanager-file-mover.service`，确认 `active`、`enabled`；没有新增业务挂载或 TCP 端口。
- 基于生产 1.6.132 相同源码修订隔离构建设置页，发布 `local-build-20261025-141904`；配置字段回传及参数错误状态码修复最终发布为 `file-hotfix-20261025-142742`。未夹带工作区其他业务改动，未执行 Git 提交。
- 经正常配置接口启用 `file_move.host_enabled`；主进程状态 `enabled/online/ready` 均为真，9 个业务根目录可访问。离线 socket 启用请求返回 400，磁盘配置保持原样。
- 配置原件与哈希清单保存在 `/app/data/.deploy/file-move-config-backups/enable-20261025-142920/`；安装、源码和配置备份分别保留最近三份。
- 正式执行器独立目录验收覆盖 ANIME 跨挂载克隆、ANIME 入库克隆、ASMR 同库重命名和真实跨文件系统复制，验证 SHA-256、COW 隔离、多文件、空目录、树内硬链接及符号链接；8 个测试目录精确清理。耗时包含校验与同步，不能用小样本推算实际吞吐。
- 启用后不注入测试配置，再次验证 `/anime_temp` 到 `/anime_delete`：实际阶段为“快速克隆、校验、清理来源”，哈希一致、源已清理；两个测试目录已清理。
- 本轮定向后端测试 72 通过、1 跳过；设置页交互测试 3 通过；前端构建、相关 Python 编译及 AST 搬运入口检查通过。未完成浏览器视觉验收、完整 PostgreSQL 业务回归、磁盘读写计数和三者联动回滚演练，不将这些算作已验收。
- 最终生产容器 `running healthy`，`/api/health` 返回 1.6.132。跨文件系统仍流式复制；已有复制操作不会中途切换为克隆。
