"""社团事实事务内的合并队列；不在此提交调用方事务。"""
from sqlalchemy import text


ENQUEUE_SQL = """
CREATE OR REPLACE FUNCTION circle_completion_enqueue(
    circles text[], codes text[], why text, full_build boolean DEFAULT false
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE cid text; seq bigint; xid bigint := txid_current();
BEGIN
    FOR cid IN SELECT DISTINCT x FROM unnest(circles) x WHERE x <> '' ORDER BY x LOOP
        INSERT INTO circle_completion_controls(circle_id) VALUES(cid) ON CONFLICT DO NOTHING;
        UPDATE circle_completion_controls SET
            requested_seq = requested_seq + CASE WHEN last_transaction_id = xid THEN 0 ELSE 1 END,
            last_transaction_id = xid, next_retry_at = NULL
        WHERE circle_id = cid RETURNING requested_seq INTO seq;
        IF full_build THEN
            UPDATE circle_completion_controls SET full_requested_seq = seq WHERE circle_id = cid;
        END IF;
        INSERT INTO circle_completion_dirty(circle_id, source_rjcode, last_seq, reasons, first_seen_at, updated_at)
        SELECT cid, x, seq, ARRAY[why], localtimestamp, localtimestamp
        FROM (SELECT DISTINCT x FROM unnest(codes) x WHERE x ~ '^RJ[0-9]+$') q
        ON CONFLICT(circle_id, source_rjcode) DO UPDATE SET
            last_seq = EXCLUDED.last_seq,
            reasons = ARRAY(SELECT DISTINCT unnest(circle_completion_dirty.reasons || EXCLUDED.reasons)),
            updated_at = EXCLUDED.updated_at;
    END LOOP;
END $$
"""

CAPTURE_SQL = """
CREATE OR REPLACE FUNCTION circle_completion_source_value(value jsonb, source_table text)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
      WHEN source_table = 'asmr_download_sessions' THEN
        jsonb_build_object('rjcode', value->'rjcode', 'local_download_ready', value->'local_download_ready',
          'local_download_root', COALESCE(NULLIF(value->>'local_download_root',''), value->'statistics'->>'download_root'),
          'local_downloaded_count', value->'local_downloaded_count')
      WHEN source_table = 'circle_completion_cover_facts' THEN
        jsonb_build_object('rjcode', value->'rjcode', 'conclusion', value->'conclusion')
      ELSE value - ARRAY['updated_at','checked_at','cached_at']
    END
$$;
CREATE OR REPLACE FUNCTION circle_completion_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rows jsonb; codes text[]; circles text[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT jsonb_agg(to_jsonb(n)) INTO rows FROM new_rows n;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT jsonb_agg(to_jsonb(o)) INTO rows FROM old_rows o;
    ELSE
        -- 只更新缓存时间、进度心跳不改变补全事实。
        WITH old_values AS (
            SELECT circle_completion_source_value(to_jsonb(o), TG_TABLE_NAME) AS value FROM old_rows o
        ), new_values AS (
            SELECT circle_completion_source_value(to_jsonb(n), TG_TABLE_NAME) AS value FROM new_rows n
        ), changed AS (
            (SELECT value FROM old_values EXCEPT SELECT value FROM new_values)
            UNION ALL (SELECT value FROM new_values EXCEPT SELECT value FROM old_values)
        ) SELECT jsonb_agg(value) INTO rows FROM changed;
    END IF;
    IF rows IS NULL THEN RETURN NULL; END IF;
    IF TG_TABLE_NAME = 'dlsite_bonus_probe_dates' THEN
        SELECT array_agg(DISTINCT w.circle_id) INTO circles
        FROM jsonb_array_elements(rows) r
        JOIN work_metadata m ON m.maker_id = r->>'maker_id' AND m.release_date = r->>'release_date'
        JOIN circle_works w ON w.canonical_rjcode = m.rjcode OR w.display_rjcode = m.rjcode
            OR w.linked_rjcodes @> jsonb_build_array(m.rjcode);
        PERFORM circle_completion_enqueue(circles, ARRAY[]::text[], TG_TABLE_NAME, true);
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'circle_completion_cover_facts' AND TG_OP <> 'UPDATE' THEN
        SELECT jsonb_agg(r) INTO rows FROM jsonb_array_elements(rows) r
            WHERE COALESCE(r->>'conclusion','unknown') <> 'unknown';
        IF rows IS NULL THEN RETURN NULL; END IF;
    END IF;
    SELECT array_agg(DISTINCT code) INTO codes FROM (
      SELECT e.value AS code FROM jsonb_array_elements(rows) r,
        LATERAL jsonb_each_text(r) e(key,value)
        WHERE e.key IN ('rjcode','canonical_rjcode','display_rjcode','linked_rjcode','original_rjcode','bonus_rjcode')
        AND e.value ~ '^RJ[0-9]+$'
      UNION SELECT a.code FROM jsonb_array_elements(rows) r,
        LATERAL jsonb_array_elements_text(CASE WHEN jsonb_typeof(r->'linked_rjcodes')='array'
            THEN r->'linked_rjcodes' ELSE '[]'::jsonb END) a(code)
        WHERE a.code ~ '^RJ[0-9]+$'
    ) extracted;
    SELECT array_agg(DISTINCT circle_id) INTO circles FROM (
        SELECT r->>'circle_id' AS circle_id FROM jsonb_array_elements(rows) r
        UNION
        SELECT w.circle_id FROM circle_works w WHERE w.canonical_rjcode = ANY(codes)
            OR w.display_rjcode = ANY(codes) OR EXISTS (
                SELECT 1 FROM unnest(codes) code WHERE w.linked_rjcodes @> jsonb_build_array(code))
        UNION
        SELECT a.circle_id FROM circle_completion_work_aliases a
            JOIN circle_completion_heads h ON h.circle_id=a.circle_id AND h.active_generation=a.generation
            WHERE a.rjcode = ANY(codes)
    ) affected WHERE circle_id IS NOT NULL AND circle_id <> '';
    PERFORM circle_completion_enqueue(circles, codes, TG_TABLE_NAME,
        TG_TABLE_NAME='circle_catalogs' OR COALESCE(cardinality(codes),0)=0);
    RETURN NULL;
END $$
"""

SOURCE_TABLES = (
    "circle_catalogs", "circle_works", "work_metadata", "work_canonical_links",
    "library_owned_works", "resource_source_probes", "circle_subtitle_target_snapshots",
    "dlsite_bonus_original_probe_states", "dlsite_bonus_probe_hit_index",
    "dlsite_bonus_probe_dates", "dlsite_bonus_probe_cache", "asmr_download_sessions", "circle_completion_cover_facts",
)


def install_change_capture(conn):
    """与建表处于同一事务；触发器覆盖 ORM、Core 和批量写入。"""
    conn.execute(text(ENQUEUE_SQL))
    conn.execute(text(CAPTURE_SQL))
    # 旧版本曾把库存索引运行态变化误当成社团事实变化，
    # 启动时主动移除遗留触发器，避免生产数据库继续全量刷新所有社团。
    for operation in ("insert", "update", "delete"):
        conn.execute(text(
            f"DROP TRIGGER IF EXISTS cc_dirty_library_index_status_{operation} "
            "ON library_index_status"
        ))
    existing = set(conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    for table in SOURCE_TABLES:
        for operation, reference in (
            ("INSERT", "NEW TABLE AS new_rows"),
            ("UPDATE", "OLD TABLE AS old_rows NEW TABLE AS new_rows"),
            ("DELETE", "OLD TABLE AS old_rows"),
        ):
            name = f"cc_dirty_{table}_{operation.lower()}"
            if name not in existing:
                conn.execute(text(f"CREATE TRIGGER {name} AFTER {operation} ON {table} "
                                  f"REFERENCING {reference} FOR EACH STATEMENT "
                                  "EXECUTE FUNCTION circle_completion_capture()"))


def enqueue_in_session(db, circle_ids, source_rjcodes=(), *, reason, full=False):
    db.execute(text("SELECT circle_completion_enqueue(:circles, :codes, :reason, :full)"),
               {"circles": sorted(set(circle_ids)), "codes": sorted(set(source_rjcodes)),
                "reason": reason, "full": full})
