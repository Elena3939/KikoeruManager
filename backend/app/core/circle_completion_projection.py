"""社团查询投影：共享业务函数生成索引，SQL 筛选分页后才读取展示 JSON。"""
from __future__ import annotations

import hashlib
from copy import deepcopy

from sqlalchemy import delete, insert, select, text

from ..models.database import (
    CircleCompletionProjection as Projection,
    CircleCompletionProjectionRow as ProjectionRow,
)
from .release_dates import is_unreleased

STATUS_KEYS = ("repairable", "downloadable", "missing", "no_source", "has_early_bonus", "no_early_bonus")
OWNED_KEYS = ("original", "simplified", "traditional", "subtitle", "bonus")
COMPARE_KEYS = ("kikoeru", "dlsite", "asmr_one", "yaas", "missing")


def projection_id(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _search_text(item):
    return " ".join(str(value or "") for value in (
        item.get("canonical_rjcode"), item.get("display_rjcode"), item.get("title"),
        *(item.get("linked_rjcodes") or []),
    )).lower()


def build_projection_rows(service, items):
    """卡片先按既有规则成组；列表保留成员，筛选后由 SQL 决定挂靠。"""
    variants = {"list": items}
    for tab in ("missing", "owned"):
        for include_dl_only in (False, True):
            variants[f"card:{tab}:{int(include_dl_only)}"] = service._filter_completion_items_for_card_tab(
                deepcopy(items), tab=tab, include_dl_only=include_dl_only,
            )
    for variant, values in variants.items():
        for position, item in enumerate(values):
            members = service._completion_group_members(item) if variant != "list" else [item]
            tags = []
            for key in STATUS_KEYS:
                if any(service._completion_item_matches_status_filter(member, key) for member in members):
                    tags.append(f"status:{key}")
            for tab in ("missing", "owned", "compare"):
                if service._filter_completion_items_for_tab(members, tab=tab, include_dl_only=True):
                    tags.append(f"tab:{tab}")
            for key in OWNED_KEYS:
                if service._filter_completion_items_for_tab(members, tab="owned", include_dl_only=True, owned_filter=key):
                    tags.append(f"owned:{key}")
            for key in COMPARE_KEYS:
                if service._filter_completion_items_for_tab(members, tab="compare", include_dl_only=True, compare_filter=key):
                    tags.append(f"compare:{key}")
            if item.get("owned") or item.get("has_downloadable_source", item.get("has_asmr_one")):
                tags.append("source_visible")
            own_codes = service._completion_bonus_own_codes(item)
            parents = []
            if item.get("is_bonus_work"):
                for candidate in (item.get("bonus_parent_rjcode"), item.get("canonical_rjcode"), *(item.get("linked_rjcodes") or [])):
                    code = service.normalize_rjcode(candidate)
                    if code and code not in own_codes and code not in parents:
                        parents.append(code)
            payload = deepcopy(item)
            compare = payload.pop("source_compare", None)
            yield dict(
                variant=variant, position=position, tags=tags,
                search_text="\n".join(_search_text(member) for member in members),
                aliases=service._completion_item_codes(item), parent_codes=parents,
                is_bonus=bool(item.get("is_bonus_work")),
                release_timestamp=float(service._completion_release_timestamp(item)),
                unreleased=bool(item.get("is_unreleased")) or is_unreleased(item.get("release_date")),
                title=str(item.get("title") or ""), member_count=len(members),
                payload=payload, compare_payload=compare,
            )


def publish_projection(key, circle_id, data_version, rows, summary, is_current, *, session_factory):
    """同事务发布；跨进程互斥，构建中再失效则整体回滚。"""
    identity = projection_id(key)
    lock_id = int(hashlib.sha256(circle_id.encode()).hexdigest()[:16], 16)
    if lock_id >= 2**63:
        lock_id -= 2**64
    with session_factory() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        if not is_current():
            return False
        if db.get(Projection, identity) is not None:
            return True
        db.add(Projection(id=identity, circle_id=circle_id, data_version=data_version,
                          summary=summary, row_count=summary["total_works"]))
        db.flush()
        batch = []
        for row in rows:
            batch.append({"projection_id": identity, **row})
            if len(batch) >= 200:
                db.execute(insert(ProjectionRow), batch)
                batch.clear()
        if batch:
            db.execute(insert(ProjectionRow), batch)
        if not is_current():
            db.rollback()
            return False
        obsolete = select(Projection.id).where(
            Projection.circle_id == circle_id,
            Projection.id != identity,
        ).order_by(Projection.updated_at.desc(), Projection.id.desc()).offset(2)
        db.execute(delete(Projection).where(Projection.id.in_(obsolete)))
        db.commit()
        return True


def projection_query(identity, *, tab="missing", include_dl_only=True, status_filters=(),
                     owned_filter="all", compare_filter="all", search="", sort="updated_desc", view_mode="list"):
    """查询仅引用轻量索引列，页窗口确定后另外读取 payload。"""
    card = view_mode == "card" and tab in {"missing", "owned"}
    variant = f"card:{tab}:{int(include_dl_only)}" if card else "list"
    required = []
    if not card:
        required.append(f"tab:{tab if tab in {'owned', 'compare'} else 'missing'}")
        if not include_dl_only:
            required.append("source_visible")
    if tab == "owned" and owned_filter in OWNED_KEYS:
        required.append(f"owned:{owned_filter}")
    if tab == "compare" and compare_filter in COMPARE_KEYS:
        required.append(f"compare:{compare_filter}")
    clauses = ["projection_id = :identity", "variant = :variant", "tags @> CAST(:required AS text[])"]
    params = dict(identity=identity, variant=variant, required=required)
    if status_filters:
        clauses.append("tags && CAST(:statuses AS text[])")
        params["statuses"] = [f"status:{key}" for key in status_filters]
    if search.strip():
        clauses.append("search_text LIKE :search ESCAPE '~'")
        params["search"] = "%" + search.strip().lower().replace("~", "~~").replace("%", "~%").replace("_", "~_") + "%"
    order = "position"
    if sort in {"release_asc", "release_desc"}:
        direction = "ASC" if sort == "release_asc" else "DESC"
        order = f'unreleased {direction}, release_timestamp {direction}, title COLLATE "C", position'
    filtered = f"""filtered AS MATERIALIZED (
        SELECT position, aliases, parent_codes, is_bonus, member_count,
               row_number() OVER (ORDER BY {order}) AS ordinal
        FROM circle_completion_projection_rows WHERE {' AND '.join(clauses)}
    )"""
    if card or tab == "compare":
        groups = """groups AS (
            SELECT position AS root, ordinal, ARRAY[position] AS members, member_count FROM filtered
        )"""
    else:
        # 先选第一个存在的候选编号，再按非特典优先、当前排序顺序决定编号所有者。
        # 候选恰好属于特典时停止挂靠，与原业务函数完全相同。
        groups = """aliases AS MATERIALIZED (
            SELECT DISTINCT ON (code) code, position, is_bonus
            FROM filtered CROSS JOIN LATERAL unnest(aliases) AS codes(code)
            ORDER BY code, is_bonus, ordinal
        ), mapped AS MATERIALIZED (
            SELECT f.position, f.ordinal,
                   CASE WHEN p.position IS NOT NULL AND NOT p.is_bonus AND p.position <> f.position
                        THEN p.position ELSE f.position END AS root
            FROM filtered f
            LEFT JOIN LATERAL (
                SELECT a.position, a.is_bonus
                FROM unnest(f.parent_codes) WITH ORDINALITY AS candidates(code, priority)
                JOIN aliases a USING (code) ORDER BY candidates.priority LIMIT 1
            ) p ON true
        ), groups AS (
            SELECT m.root, root.ordinal, array_agg(m.position ORDER BY m.ordinal) AS members,
                   count(*)::integer AS member_count
            FROM mapped m JOIN filtered root ON root.position = m.root
            GROUP BY m.root, root.ordinal
        )"""
    statement = f"""WITH {filtered}, {groups}, stats AS (
        SELECT count(*)::integer AS total, COALESCE(sum(member_count), 0)::integer AS filtered_count FROM groups
    ), bounds AS (
        SELECT *, greatest(1, (total + :size - 1) / :size) AS page_count,
               least(:page, greatest(1, (total + :size - 1) / :size)) AS page FROM stats
    ), page_window AS (
        SELECT root, members, ordinal FROM groups ORDER BY ordinal
        LIMIT :size OFFSET (SELECT (page - 1) * :size FROM bounds)
    ) SELECT bounds.*, page_window.root, page_window.members FROM bounds LEFT JOIN page_window ON true ORDER BY page_window.ordinal"""
    return statement, params, card


def read_projection_page(key, page, page_size, *, session_factory, **query):
    identity = projection_id(key)
    with session_factory() as db:
        header = db.execute(select(Projection).where(Projection.id == identity).with_for_update(read=True)).scalar_one_or_none()
        if header is None:
            return None
        statement, params, card = projection_query(identity, **query)
        params.update(page=max(1, page), size=max(1, page_size))
        windows = db.execute(text(statement), params).mappings().all()
        bounds = windows[0]
        positions = {position for window in windows for position in (window["members"] or [])}
        columns = [ProjectionRow.position, ProjectionRow.payload]
        if query.get("tab") == "compare":
            columns.append(ProjectionRow.compare_payload)
        rows = db.execute(select(*columns).where(
            ProjectionRow.projection_id == identity, ProjectionRow.variant == params["variant"],
            ProjectionRow.position.in_(positions),
        )).mappings().all() if positions else []
        by_position = {}
        for row in rows:
            payload = row["payload"]
            if query.get("tab") == "compare":
                payload["source_compare"] = row["compare_payload"]
            by_position[row["position"]] = payload
        result = []
        for window in windows:
            if window["root"] is None:
                continue
            item = by_position[window["root"]]
            if not card and query.get("tab") != "compare" and len(window["members"]) > 1:
                bonuses = item.setdefault("bonus_works", [])
                seen = {str(bonus.get("display_rjcode") or bonus.get("canonical_rjcode") or "").upper() for bonus in bonuses}
                for position in window["members"]:
                    if position == window["root"]:
                        continue
                    bonus = by_position[position]
                    code = str(bonus.get("display_rjcode") or bonus.get("canonical_rjcode") or "").upper()
                    if code not in seen:
                        bonuses.append(bonus)
                        seen.add(code)
            result.append(item)
        summary = {**header.summary, "filtered_count": bounds["filtered_count"]}
        if query.get("tab") == "missing":
            summary["missing_count"] = bounds["filtered_count"]
        return dict(rows=result, summary=summary, total=bounds["total"],
                    page=bounds["page"], page_count=bounds["page_count"])
