# 数据库迁移执行说明

- Docker 单镜像启动时会先执行 `python -m alembic upgrade head`，再启动应用服务。
- 应用启动期仍保留 `init_db()` 里的兼容迁移兜底，用来修复历史运行库中已经存在但字段类型落后的表结构。
- `init_db()` 只有在兼容迁移全部成功后才会标记初始化完成；字段修复失败必须阻断启动，不能让后续写入继续打到旧结构。
- 新增数据库结构变更时必须同时考虑两条路径：Alembic migration 负责正式版本迁移，`backend/app/models/database.py` 的兼容迁移负责没有 `alembic_version` 的历史库兜底。
- 对大表执行类型变更时要用 `ALTER TABLE ... TYPE ... USING ...`，并在低峰期发布；例如 `dlsite_bonus_probe_cache.price` / `wishlist_count` 必须保持 `BIGINT`，迁移后要复查 `information_schema.columns.udt_name = int8`，避免特典探测缓存落库时发生 32 位整数溢出。
