"""固定格式链接表解析，不访问网络，也不将完整工作表装入内存。"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import defaultdict
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REQUIRED = {"RJcode", "MEGA链接"}
MAX_XML_BYTES = 512 * 1024 * 1024
MAX_ROWS = 200_000
MAX_FILES_PER_ROW = 2000


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def normalize_code(value):
    code = str(value or "").strip().upper()
    return code if re.fullmatch(r"RJ\d{6,8}", code) else ""


def mega_file_url(value):
    value = str(value or "").strip()
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.hostname not in {"mega.nz", "mega.io", "www.mega.nz"}
            or parts.username or parts.password or parts.port):
        raise ValueError("仅接受 HTTPS MEGA 文件分享")
    modern = re.fullmatch(r"/file/([A-Za-z0-9_-]+)", parts.path)
    if modern and re.fullmatch(r"[A-Za-z0-9_-]+", parts.fragment):
        return value
    if parts.path in {"", "/"} and re.fullmatch(r"![A-Za-z0-9_-]+![A-Za-z0-9_-]+", parts.fragment):
        return value
    raise ValueError("MEGA 文件链接缺少文件编号或密钥")


def group_identity(name):
    normalized = re.sub(r"\.(e_x_e_|r_a_r_|z_i_p_)$", lambda m: "." + m[1].replace("_", ""), name,
                        flags=re.I)
    tags = [tag.strip() for tag in re.findall(r"【([^】]+)】", normalized)
            if not re.match(r"^(?:RJ\d+$|Size[:：]|\d{4}[-_]\d{2}[-_]\d{2}$)", tag, re.I)]
    part = re.search(r"\.part(\d+)\.(?:exe|rar|zip|7z)$", normalized, re.I)
    numeric = re.search(r"\.(\d{3})$", normalized)
    split_zip = re.search(r"\.z(\d{2})$", normalized, re.I)
    volume = int((part or numeric or split_zip)[1]) if (part or numeric or split_zip) else None
    if part:
        base, kind = normalized[:part.start()], "part"
    elif numeric:
        base, kind = normalized[:numeric.start()], "numeric"
    elif split_zip:
        base, kind = normalized[:split_zip.start()], "zip"
    else:
        base = re.sub(r"\.(exe|rar|zip|7z)$", "", normalized, flags=re.I)
        kind = "single"
    return {"base": base, "tags": tags, "volume": volume, "kind": kind,
            "part_digits": part[1] if part else ""}


def build_groups(files):
    """同名不同大小保留独立选择；分卷按原表次序拆组，不改卷名。"""
    buckets = defaultdict(list)
    identities = {f["id"]: group_identity(f["name"]) for f in files if not f["excluded"]}
    zip_bases = {i["base"] for i in identities.values() if i["kind"] == "zip"}
    for file in files:
        if file["excluded"]:
            continue
        ident = identities[file["id"]]
        kind = "zip" if ident["kind"] == "single" and ident["base"] in zip_bases else ident["kind"]
        buckets[(tuple(ident["tags"]), ident["base"], kind)].append(file)
    # 同一卷同时出现 part01 和 part1 时，按编号格式拆成独立归档集合。
    separated = {}
    split_keys = set()
    for key, members in buckets.items():
        spellings = defaultdict(set)
        for file in members:
            ident = identities[file["id"]]
            if ident["part_digits"]:
                spellings[ident["volume"]].add(ident["part_digits"])
        split = any(len(values) > 1 for values in spellings.values())
        if split:
            split_keys.add(key)
        for file in members:
            digits = identities[file["id"]]["part_digits"]
            style = len(digits) if split and len(digits) > 1 else 0
            separated.setdefault((*key, style), []).append(file)
    groups, errors = [], []
    for (tags, base, kind, style), members in separated.items():
        by_name = defaultdict(dict)
        for file in members:
            by_name[file["name"]].setdefault(file["size_bytes"] or 0, []).append(file)
        logical_files = []
        for name, sizes in by_name.items():
            for size, candidates in sizes.items():
                logical_files.append(dict(name=name, size_bytes=size or 0,
                                          candidate_ids=[f["id"] for f in candidates]))
        collision = len({f["name"].casefold() for f in logical_files}) != len(logical_files)
        if collision and kind == "single":
            variants = [[file] for file in logical_files]
        elif collision:
            # 各卷的第 N 条记录组成第 N 组；唯一的卷可供各组共用。
            # 不用大小推断配套关系，预览明确提示用户核对。
            slots = defaultdict(list)
            for file in logical_files:
                slots[file["name"].casefold()].append(file)
            variants = [[choices[0] if len(choices) == 1 else choices[index]
                         for choices in slots.values() if len(choices) == 1 or index < len(choices)]
                        for index in range(max(map(len, slots.values())))]
        else:
            variants = [logical_files]
        for index, variant in enumerate(variants):
            volumes = [group_identity(file["name"])["volume"] for file in variant
                       if group_identity(file["name"])["volume"] is not None]
            complete = not volumes or (len(set(volumes)) == len(volumes) and all(
                volume == number for number, volume in enumerate(sorted(volumes), 1)))
            if kind == "zip" and not any(re.search(r"\.zip$", f["name"], re.I) for f in variant):
                complete = False
            if not complete and not collision:
                errors.append(f"资源组 {base} 存在重复、不连续卷号或缺少 ZIP 主文件")
            label = " · ".join(tags) or "原档"
            identity = [list(tags), base, kind]
            if (tags, base, kind) in split_keys:
                identity.append(["part_digits", style])
                label += " · " + ("part" + "1".zfill(style))
            if collision:
                identity.append([[f["name"], f["size_bytes"]] for f in variant])
                label += f" · 同名文件 {index + 1}" if kind == "single" else f" · 分卷方案 {index + 1}"
            groups.append(dict(id=digest(identity)[:24], name=label, archive_name=base,
                               archive_kind=kind,
                               files=variant, size_bytes=sum(f["size_bytes"] for f in variant),
                               complete=complete, selected=False,
                               notice=("同名文件可分别选择，保存时自动编号" if kind == "single" else
                                       "同名分卷按表内顺序分组，请核对配套关系；各组独立目录")
                               if collision else ""))
    # 名称预留覆盖整个修订，不依赖落盘状态；重试时不会重复追加编号。
    used = {f["name"].casefold() for f in files if not f["excluded"]}
    seen, seen_names = {}, set()
    for group in groups:
        for file in group["files"]:
            name = file["name"]
            identity = (name, file["size_bytes"])
            if group["archive_kind"] != "single":
                continue
            if identity in seen:
                if seen[identity]:
                    file["save_name"] = seen[identity]
                continue
            if name.casefold() in seen_names:
                stem, dot, suffix = name.rpartition(".")
                stem, extension = (stem, dot + suffix) if dot else (name, "")
                number = 2
                while f"{stem} ({number}){extension}".casefold() in used:
                    number += 1
                file["save_name"] = f"{stem} ({number}){extension}"
                used.add(file["save_name"].casefold())
            seen[identity] = file.get("save_name")
            seen_names.add(name.casefold())
    if not groups:
        errors.append("没有可下载资源组")
    return groups, errors


def parse_record(cells, row_number):
    code = normalize_code(cells.get("RJcode"))
    if not code:
        return None
    metadata = {key: ("" if str(value).strip().lower() == "null" else str(value).strip())
                for key, value in cells.items() if key != "MEGA链接"}
    errors, files = [], []
    try:
        raw = json.loads(cells.get("MEGA链接", ""))
        entries = raw["C"]
        if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES_PER_ROW:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        return dict(rjcode=code, source_row=row_number, metadata=metadata, files=[],
                    groups=[], errors=["文件清单 JSON 无效或文件数量超限"], content_hash=digest(cells))
    logical = {}
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"第 {ordinal + 1} 个文件记录格式无效")
            continue
        name = str(entry.get("F") or "").strip()
        excluded = name.lower().endswith(".par2")
        try:
            url = mega_file_url(entry.get("L"))
        except (ValueError, TypeError):
            url = str(entry.get("L") or "")
            if not excluded:
                errors.append(f"第 {ordinal + 1} 个文件链接无效")
        raw_size = "" if entry.get("S") is None else str(entry["S"])
        size = int(raw_size) if re.fullmatch(r"\d+", raw_size) else None
        if size is not None and size > 2**63 - 1:
            size = None
        unsafe = (not name or name in {".", ".."} or name.endswith((".", " "))
                  or bool(re.search(r'[<>:"/\\|?*\x00-\x1f]', name))
                  or bool(re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I)))
        if not excluded:
            if unsafe:
                errors.append(f"第 {ordinal + 1} 个文件名不能安全落盘")
        identity = (name, size, url)
        if identity in logical:
            continue
        candidate_id = digest([code, name, size, url])[:32]
        logical[identity] = candidate_id
        files.append(dict(id=candidate_id, name=name, size_bytes=size, raw_size=raw_size,
                          url=url, ordinal=ordinal, excluded=excluded))
    groups, group_errors = build_groups(files)
    errors.extend(group_errors)
    # 文件顺序不是版本身份；候选的默认优先级仍按原表顺序保存。
    fingerprint = digest([metadata, sorted((f["name"], f["raw_size"], f["url"]) for f in files)])
    return dict(rjcode=code, source_row=row_number, metadata=metadata, files=files,
                groups=groups, errors=list(dict.fromkeys(errors)), content_hash=fingerprint,
                file_count=len(entries), par2_count=sum(
                    str(f.get("F") or "").lower().endswith(".par2") for f in entries if isinstance(f, dict)))


def _sheet_rows(archive, target, shared):
    headers = None
    with archive.open(target) as stream:
        root = None
        for event, elem in ET.iterparse(stream, events=("start", "end")):
            if root is None:
                root = elem
            if event != "end" or elem.tag != NS + "row":
                continue
            number = int(elem.get("r", "0"))
            if number > MAX_ROWS + 1:
                raise ValueError("Excel 行数超过 200000")
            values = {}
            for cell in elem:
                col = re.sub(r"\d", "", cell.get("r", ""))
                if cell.get("t") == "s":
                    values[col] = shared[int(cell.findtext(NS + "v", "-1"))]
                elif cell.get("t") == "inlineStr":
                    values[col] = "".join(t.text or "" for t in cell.iter(NS + "t"))
                else:
                    values[col] = cell.findtext(NS + "v", "")
                if cell.find(NS + "f") is not None:
                    raise ValueError(f"第 {number} 行包含不支持的公式")
            if headers is None:
                headers = {col: value.strip() for col, value in values.items()}
                if not REQUIRED.issubset(headers.values()):
                    raise ValueError("缺少 RJcode 或 MEGA链接 列")
            else:
                yield number, {headers.get(col, col): value for col, value in values.items()}
            elem.clear()
            # sheetData 持有 row 的空壳，逐行移除以控制内存。
            sheet_data = root.find(NS + "sheetData")
            if sheet_data is not None:
                sheet_data.clear()


def iter_records(path, on_total=None):
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_XML_BYTES:
            raise ValueError("Excel 解压大小超过 512 MiB")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            with archive.open("xl/sharedStrings.xml") as stream:
                for _, elem in ET.iterparse(stream, events=("end",)):
                    if elem.tag == NS + "si":
                        shared.append("".join(t.text or "" for t in elem.iter(NS + "t")))
                        elem.clear()
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.find(NS + "sheets")
        if sheets is None or len(sheets) != 1:
            raise ValueError("当前格式要求一个工作表")
        rel_id = sheets[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next((rel.get("Target") for rel in relationships if rel.get("Id") == rel_id), "")
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if ".." in target.split("/") or target not in archive.namelist():
            raise ValueError("工作表关系无效")
        if on_total is not None:
            # 仅预读 RJ 标识，不解析文件 JSON，不依赖可能包含空行的 dimension。
            codes = {code for _, values in _sheet_rows(archive, target, shared)
                     if (code := normalize_code(values.get("RJcode")))}
            on_total(len(codes))
            del codes
        for number, values in _sheet_rows(archive, target, shared):
            yield number, parse_record(values, number)
