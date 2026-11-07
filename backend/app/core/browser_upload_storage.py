"""上传暂存与本地原子落地。所有大文件操作均有界流式执行。"""
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

CHUNK_SIZE = 8 * 1024 * 1024


def relative_name(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('上传路径为空或过长')
    parts = value.split('/')
    if any(p in ('', '.', '..') or re.search(r'[\\\x00-\x1f<>:"|?*]', p)
           or p.endswith((' ', '.')) or len(p.encode('utf-8')) > 255
           or re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
           for p in parts):
        raise ValueError('上传路径包含非法名称或路径跳转')
    return value


def local_target(root, incoming):
    root = Path(root).resolve(strict=True)
    candidate = Path(incoming) if incoming else root
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.absolute()
    if not candidate.is_relative_to(root):
        raise PermissionError('上传目标超出库存范围')
    # 不跟随任何一级符号链接／Windows junction，包含库存内部链接。
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise PermissionError('上传目标包含符号链接或目录联接')
    if not candidate.resolve().is_relative_to(root):
        raise PermissionError('上传目标越界')
    return candidate


def digest_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    pending = path.with_suffix('.new')
    with pending.open('w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(pending, path)


def read_checkpoint(receipt):
    if not receipt.exists():
        return {'offset': 0, 'chunks': []}
    with receipt.open('rb') as source:
        first = json.loads(source.readline())
        if first.get('version') != 2:
            return first
        saved = {'offset': 0, 'chunks': []}
        valid_end = source.tell()
        for line in source:
            if not line.endswith(b'\n'):
                break
            try:
                chunk = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                break
            if chunk.get('offset') != saved['offset'] or not 0 < chunk.get('size', 0) <= CHUNK_SIZE:
                break
            saved['chunks'].append(chunk)
            saved['offset'] += chunk['size']
            valid_end += len(line)
    # 进程在追加回执时中断，只丢弃未确认的尾记录。
    if receipt.stat().st_size != valid_end:
        with receipt.open('r+b') as output:
            output.truncate(valid_end)
            output.flush()
            os.fsync(output.fileno())
    return saved


def write_checkpoint(receipt, checkpoint):
    pending = receipt.with_suffix('.new')
    with pending.open('w', encoding='utf-8', newline='\n') as output:
        output.write('{"version":2}\n')
        for chunk in checkpoint['chunks']:
            output.write(json.dumps(chunk, separators=(',', ':')) + '\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(pending, receipt)
    from .file_move_protocol import fsync_directory
    fsync_directory(receipt.parent)


def verify_received_file(path, receipt):
    saved = read_checkpoint(receipt)
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in saved['chunks']:
            data = source.read(chunk['size'])
            if len(data) != chunk['size'] or hashlib.sha256(data).hexdigest() != chunk['sha256']:
                raise ValueError('已确认分块校验失败，请重新选择来源恢复上传')
            digest.update(data)
        if source.tell() != saved['offset'] or source.read(1):
            raise ValueError('上传文件长度与确认回执不一致')
    return digest.hexdigest()


def receive_chunk(path, offset, data, digest, expected_size, receipt_path=None, checkpoint=None, hasher=None):
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != digest:
        raise ValueError('分块 SHA-256 校验失败，未接收该块')
    receipt = Path(receipt_path) if receipt_path else path.with_suffix('.json')
    checkpoint = checkpoint if checkpoint is not None else read_checkpoint(receipt)
    confirmed = checkpoint['offset']
    if offset < confirmed:
        match = next((c for c in checkpoint['chunks'] if c['offset'] == offset), None)
        if not match or match['size'] != len(data) or match['sha256'] != digest:
            raise ValueError('重复分块与已确认数据不一致')
        return checkpoint
    if offset != confirmed or offset + len(data) > expected_size:
        raise ValueError(f'分块位置错误，期望偏移 {confirmed}')
    if len(data) != min(CHUNK_SIZE, expected_size - offset):
        raise ValueError('分块长度错误')
    if shutil.disk_usage(path.parent).free < len(data) + 16 * 1024 * 1024:
        raise OSError('暂存空间不足，已保留确认断点')
    with path.open('r+b' if path.exists() else 'w+b') as output:
        output.seek(confirmed)
        output.truncate()
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    chunk = {'offset': offset, 'size': len(data), 'sha256': digest}
    modern = False
    if receipt.exists():
        with receipt.open('rb') as source:
            modern = source.readline().startswith(b'{"version":2}')
    if not modern:
        write_checkpoint(receipt, checkpoint)
    with receipt.open('ab') as output:
        output.write((json.dumps(chunk, separators=(',', ':')) + '\n').encode('utf-8'))
        output.flush()
        os.fsync(output.fileno())
    checkpoint['chunks'].append(chunk)
    checkpoint['offset'] += len(data)
    if hasher is not None and hasher['offset'] == offset:
        hasher['digest'].update(data)
        hasher['offset'] += len(data)
    return checkpoint


def recover_checkpoint(path, receipt_path=None, full=True):
    receipt = Path(receipt_path) if receipt_path else path.with_suffix('.json')
    if not path.exists() or not receipt.exists():
        empty = {'offset': 0, 'chunks': []}
        if receipt.exists():
            write_checkpoint(receipt, empty)
        return empty
    saved = read_checkpoint(receipt)
    verified = {'offset': 0, 'chunks': []} if full else {'offset': saved['offset'], 'chunks': list(saved['chunks'])}
    with path.open('rb') as source:
        chunks = saved['chunks'] if full else list(reversed(saved['chunks']))
        for chunk in chunks:
            source.seek(chunk['offset'])
            data = source.read(chunk['size'])
            valid = len(data) == chunk['size'] and hashlib.sha256(data).hexdigest() == chunk['sha256']
            if not full:
                if valid:
                    break
                verified['chunks'].pop()
                verified['offset'] = chunk['offset']
                continue
            if chunk['offset'] != verified['offset'] or not valid:
                break
            verified['chunks'].append(chunk)
            verified['offset'] += len(data)
    with path.open('r+b') as output:
        output.truncate(verified['offset'])
    if verified != saved:
        write_checkpoint(receipt, verified)
    return verified


def install_local(root, target, relative_path, source, expected_hash, decision, check_active, progress):
    from .staged_file_move import _check_scope
    original_check = check_active

    def check_active():
        _check_scope()
        original_check()

    check_active()
    destination = local_target(root, str(Path(target) / relative_name(relative_path)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = local_target(root, str(destination))
    if source.parent == destination.parent:
        h = hashlib.sha256()
        copied = 0
        with source.open('rb') as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b''):
                check_active()
                h.update(chunk)
                copied += len(chunk)
                progress(copied)
        if h.hexdigest() != expected_hash:
            raise ValueError('写入库存校验失败')
        check_active()
        if decision != 'replace' and destination.exists():
            raise FileExistsError('目标文件已存在')
        from .fs_utils import publish_path
        publish_path(source, destination, overwrite=decision == 'replace')
        return str(destination)
    pending = destination.parent / ('.kikoerumanager-upload-' + uuid.uuid4().hex + '.part')
    owned = None

    def created(value):
        nonlocal owned
        owned = value

    try:
        h = hashlib.sha256()
        copied = 0
        from .fs_utils import copy_path_exclusive_sync
        copy_path_exclusive_sync(source, pending, checkpoint=check_active, on_created=created)
        with pending.open('rb') as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b''):
                check_active()
                h.update(chunk)
                copied += len(chunk)
                progress(copied)
        if h.hexdigest() != expected_hash:
            raise ValueError('写入库存校验失败')
        check_active()
        destination = local_target(root, str(destination))
        if decision == 'replace':
            if destination.exists() and not destination.is_file():
                raise FileExistsError('目标类型已改变，请重新选择冲突处理')
            os.replace(pending, destination)
        else:
            # 不覆盖提交时并发出现的文件，硬链接为原子的 no-clobber 提交。
            os.link(pending, destination)
            pending.unlink()
        return str(destination)
    finally:
        if owned is not None and os.path.lexists(pending):
            from .file_move_protocol import identity
            actual = identity(pending)
            if all(actual[key] == owned[key] for key in ('device', 'inode', 'mode')):
                pending.unlink()
