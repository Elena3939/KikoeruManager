"""上传暂存与本地原子落地。所有大文件操作均有界流式执行。"""
import hashlib
import json
import os
import re
import shutil
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


def receive_chunk(path, offset, data, digest, expected_size):
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != digest:
        raise ValueError('分块 SHA-256 校验失败，未接收该块')
    receipt = path.with_suffix('.json')
    checkpoint = json.loads(receipt.read_text('utf-8')) if receipt.exists() else {'offset': 0, 'chunks': []}
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
    checkpoint['chunks'].append({'offset': offset, 'size': len(data), 'sha256': digest})
    checkpoint['offset'] += len(data)
    atomic_json(receipt, checkpoint)
    return checkpoint


def recover_checkpoint(path):
    receipt = path.with_suffix('.json')
    if not path.exists() or not receipt.exists():
        return {'offset': 0, 'chunks': []}
    saved = json.loads(receipt.read_text('utf-8'))
    verified = {'offset': 0, 'chunks': []}
    with path.open('rb') as source:
        for chunk in saved['chunks']:
            data = source.read(chunk['size'])
            if chunk['offset'] != verified['offset'] or hashlib.sha256(data).hexdigest() != chunk['sha256']:
                break
            verified['chunks'].append(chunk)
            verified['offset'] += len(data)
    with path.open('r+b') as output:
        output.truncate(verified['offset'])
    atomic_json(receipt, verified)
    return verified


def install_local(root, target, relative_path, source, expected_hash, decision, check_active, progress):
    destination = local_target(root, str(Path(target) / relative_name(relative_path)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = local_target(root, str(destination))
    pending = destination.parent / ('.kikoerumanager-upload-' + source.stem + '.part')
    try:
        h = hashlib.sha256()
        copied = 0
        with source.open('rb') as input_file, pending.open('xb') as output:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b''):
                check_active()
                output.write(chunk)
                h.update(chunk)
                copied += len(chunk)
                progress(copied)
            output.flush()
            os.fsync(output.fileno())
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
        pending.unlink(missing_ok=True)
