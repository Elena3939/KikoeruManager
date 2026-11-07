"""一份作品数据、轻量展示索引；页窗口与发布头使用同一个 SQL 快照。"""
from __future__ import annotations

import hashlib
import orjson
from sqlalchemy import text

from .circle_completion_projection import build_projection_rows, projection_query


def fingerprint(value):
    return hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()


def build_normalized_rows(service, items, *, order_keys=None):
    entities, aliases, groups, members = {}, {}, {}, {}
    for item in items:
        code = item["canonical_rjcode"]
        payload = {key: value for key, value in item.items() if key not in ("source_compare", "bonus_works")}
        compare = item.get("source_compare")
        entities[code] = dict(canonical_rjcode=code, payload=payload, compare_payload=compare,
                              fingerprint=fingerprint([payload, compare]))
        for alias in service._completion_item_codes(item):
            aliases[code, alias] = dict(canonical_rjcode=code, rjcode=alias)
    for row in build_projection_rows(service, items, lightweight=True):
        payload = row.pop("payload")
        row.pop("compare_payload")
        code = payload["canonical_rjcode"]
        row["sort_key"] = (order_keys or {}).get(code, "")
        if order_keys is not None:
            # 稳定身份与排序分开：插入新作不重写整圈 position。
            row["position"] = int(code[2:])
        key = row["variant"], code
        group_members = service._completion_group_members(payload) if row["variant"] != "list" else [payload]
        member_rows = []
        for order, member in enumerate(group_members):
            member_code = member["canonical_rjcode"]
            presentation = {key: member[key] for key in ("completion_card_dimmed", "completion_card_mixed_group") if key in member}
            value = dict(variant=row["variant"], group_key=code, canonical_rjcode=member_code,
                         member_order=order, presentation=presentation)
            member_rows.append(value)
            members[row["variant"], code, member_code] = value
        groups[key] = dict(**row, group_key=code, fingerprint=fingerprint([row, member_rows]))
    return entities, aliases, groups, members


def page_statement(**query):
    statement, params, card = projection_query("", **query)
    statement = statement.replace("WITH filtered", "filtered", 1).replace(
        "FROM circle_completion_projection_rows", "FROM circle_completion_groups"
    ).replace("projection_id = :identity", "circle_id = :circle AND generation = (SELECT active_generation FROM head)")
    if query.get("sort", "updated_desc") not in ("release_asc", "release_desc"):
        statement = statement.replace("OVER (ORDER BY position)", 'OVER (ORDER BY sort_key DESC, position)')
    statement = statement[:statement.index(
        " SELECT bounds.*, page_window.root, page_window.members FROM bounds"
    )]
    sql = """WITH head AS MATERIALIZED (
        SELECT c.circle_id, c.circle_name, h.active_generation, h.revision, h.summary, h.as_of,
               COALESCE(h.applied_seq, 0) AS applied_seq, COALESCE(ctrl.requested_seq, 0) AS requested_seq,
               COALESCE(ctrl.last_error, '') AS last_error
        FROM circle_catalogs c LEFT JOIN circle_completion_heads h USING(circle_id)
        LEFT JOIN circle_completion_controls ctrl USING(circle_id) WHERE c.circle_id=:circle
    ), """ + statement + """
    SELECT head.*, bounds.*, w.root, payloads.entries
    FROM head CROSS JOIN bounds LEFT JOIN page_window w ON true
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_object(
            'position', g.position, 'member_order', m.member_order,
            'payload', s.payload || m.presentation,
            'compare_payload', CASE WHEN :with_compare THEN s.compare_payload ELSE NULL END
        ) ORDER BY g.position=w.root DESC, array_position(w.members,g.position), m.member_order) AS entries
        FROM circle_completion_groups g
        JOIN circle_completion_group_members m USING(circle_id,generation,variant,group_key)
        JOIN circle_completion_work_states s USING(circle_id,generation,canonical_rjcode)
        WHERE g.circle_id=:circle AND g.generation=head.active_generation AND g.variant=:variant
              AND g.position=ANY(w.members)
    ) payloads ON true ORDER BY w.ordinal
    """
    params.pop("identity")
    params["with_compare"] = query.get("tab") == "compare"
    return sql, params, card


def read_page(db, circle_id, *, page=1, page_size=10, **query):
    sql, params, card = page_statement(**query)
    params.update(circle=circle_id, page=max(1, int(page)), size=max(1, min(1000, int(page_size))))
    windows = db.execute(text(sql), params).mappings().all()
    if not windows:
        raise ValueError("社团索引不存在")
    header = windows[0]
    rows = []
    compare = query.get("tab") == "compare"
    for window in windows:
        entries = window["entries"] or []
        if not entries:
            continue
        root = next(entry["payload"] for entry in entries
                    if entry["position"] == window["root"] and entry["member_order"] == 0)
        if compare:
            root["source_compare"] = entries[0]["compare_payload"]
        else:
            seen = {str(root.get("display_rjcode") or root["canonical_rjcode"]).upper()}
            bonuses = []
            for entry in entries:
                item = entry["payload"]
                code = str(item.get("display_rjcode") or item["canonical_rjcode"]).upper()
                if code not in seen:
                    bonuses.append(item)
                    seen.add(code)
            if bonuses:
                root["bonus_works"] = bonuses
        rows.append(root)
    summary = published_header(header, query.get("include_dl_only", True))
    summary["filtered_count"] = header["filtered_count"]
    if query.get("tab", "missing") == "missing":
        summary["missing_count"] = header["filtered_count"]
    return dict(**summary, rows=rows, total=header["total"], page=header["page"],
                page_count=header["page_count"], page_size=params["size"])


def read_selection(db, circle_id, *, details=False, **query):
    """全选只投影必要字段；定位使用与分页相同的筛选、挂靠及排序。"""
    sql, params, _ = page_statement(**{**query, "view_mode": "list"})
    sql = sql[:sql.index(", stats AS (")]
    fields = ("canonical_rjcode", "display_rjcode", "title", "owned", "local_owned", "server_owned",
              "has_downloadable_source", "has_asmr_one", "is_bonus_work", "early_bonus_status",
              "is_unreleased", "release_date", "original_release_date", "bonus_parent_rjcode")
    payload = "s.payload" if details else "jsonb_build_object(" + ",".join(
        f"'{field}',s.payload->'{field}'" for field in fields) + ")"
    sql += f""", selected AS (
        SELECT {payload} AS payload, f.aliases, root.group_key AS parent,
               dense_rank() OVER (ORDER BY gr.ordinal)::integer - 1 AS group_index,
               f.ordinal
        FROM filtered f JOIN groups gr ON f.position=ANY(gr.members)
        JOIN circle_completion_groups root ON root.circle_id=:circle
             AND root.generation=(SELECT active_generation FROM head)
             AND root.variant=:variant AND root.position=gr.root
        JOIN circle_completion_work_states s ON s.circle_id=:circle
             AND s.generation=root.generation AND s.canonical_rjcode=(
                 SELECT group_key FROM circle_completion_groups WHERE circle_id=:circle
                 AND generation=root.generation AND variant=:variant AND position=f.position)
    ) SELECT head.*, selected.* FROM head LEFT JOIN selected ON true ORDER BY selected.ordinal"""
    params.update(circle=circle_id)
    records = db.execute(text(sql), params).mappings().all()
    if not records:
        raise ValueError("社团索引不存在")
    return published_header(records[0], query.get("include_dl_only", True)), [
        dict(row) for row in records if row["payload"] is not None]


def published_header(header, include_dl_only=True):
    stored = header["summary"] or {}
    summary = dict(stored.get("all" if include_dl_only else "visible", stored))
    for key in ("total_works", "filtered_count", "local_owned_count", "server_owned_count", "owned_count",
                "missing_count", "downloadable_count", "dl_only_count", "dl_count", "unreleased_count",
                "new_works_count", "bonus_works_count"):
        summary.setdefault(key, 0)
    summary.setdefault("owned_stats", dict.fromkeys(("total", "original", "simplified", "traditional", "subtitle", "bonus"), 0))
    summary.setdefault("compare_stats", dict.fromkeys(("total", "kikoeru", "dlsite", "asmr_one", "yaas", "missing"), 0))
    summary.setdefault("status_filter_counts", {"missing": {}, "owned": {}})
    revision = int(header["revision"] or 0)
    pending = header["requested_seq"] > header["applied_seq"] or not revision
    status = "failed" if header["last_error"] else "building" if not revision else "stale" if pending else "ready"
    summary.update(circle_id=header["circle_id"], circle_name=header["circle_name"])
    return dict(**summary,
                status=status, revision=revision, pending_changes=pending,
                as_of=header["as_of"].isoformat() if header["as_of"] else None,
                data_version=f"{header['active_generation'] or 'building'}/{revision}")


def read_summary(db, circle_id, *, include_dl_only=True):
    sql, params, _ = page_statement()
    sql = sql[:sql.index(", filtered AS")]+" SELECT * FROM head"
    header = db.execute(text(sql), {"circle": circle_id}).mappings().first()
    if header is None:
        raise ValueError("社团索引不存在")
    return published_header(header, include_dl_only)


def read_recent(sessions, keyword="", limit=30):
    """单次查询发布摘要，避免目录请求扫描所有社团作品。"""
    from sqlalchemy import select, func
    from ..models.database import CircleCatalog, CircleCompletionHead as Head, CircleCompletionControl as Control
    safe_limit = max(1, min(1000, int(limit)))
    statement = select(CircleCatalog, Head, Control).outerjoin(Head,
        Head.circle_id == CircleCatalog.circle_id).outerjoin(Control,
        Control.circle_id == CircleCatalog.circle_id)
    if keyword:
        escaped = keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        statement = statement.where(func.concat(CircleCatalog.circle_name_normalized, " ",
            CircleCatalog.circle_name, " ", CircleCatalog.circle_id).ilike(f"%{escaped}%", escape="!"))
    statement = statement.order_by(CircleCatalog.last_indexed_at.desc()).limit(safe_limit * 2 + 16)
    output, seen = [], set()
    with sessions() as db:
        for catalog, head, control in db.execute(statement):
            key = catalog.circle_name_normalized or catalog.circle_id
            if key in seen:
                continue
            seen.add(key)
            summary = published_header(dict(circle_id=catalog.circle_id, circle_name=catalog.circle_name,
                summary=head.summary if head else {}, revision=head.revision if head else 0,
                active_generation=head.active_generation if head else None, as_of=head.as_of if head else None,
                applied_seq=head.applied_seq if head else 0, requested_seq=control.requested_seq if control else 0,
                last_error=control.last_error if control else ""))
            item = {**catalog.to_dict(), **summary}
            item.update(dl_works=summary["dl_count"], server_owned=summary["owned_count"],
                server_owned_count=summary["owned_count"], kikoeru_owned_count=summary["server_owned_count"],
                missing=summary["missing_count"], new_works_count=summary.get("email_works_count", 0),
                new_works_48h_count=summary["new_works_count"], new_works_24h_count=summary["new_works_count"])
            output.append(item)
            if len(output) == safe_limit:
                break
    return output
