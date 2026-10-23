"""一次扫描的过滤计划；固定规则和深度下工作量与条目数量成正比。"""
import os
import re


def scan_tree(root, checkpoint=lambda: None):
    items, audio = [], {}
    stack = [root]
    audio_exts = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac'}
    while stack:
        directory = stack.pop()
        checkpoint()
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(items) % 256 == 0:
                    checkpoint()
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)
                items.append({"path": entry.path, "relative_path": os.path.relpath(entry.path, root).replace('\\', '/'),
                              "name": entry.name, "type": "dir" if is_dir else "file",
                              "size": None if is_dir else stat.st_size})
                if is_dir:
                    stack.append(entry.path)
                else:
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in audio_exts:
                        audio[ext[1:]] = audio.get(ext[1:], 0) + 1
    return items, audio


def plan_filter(items, rules, filter_dirs, checkpoint=lambda: None):
    compiled = []
    for rule in rules:
        if rule.enabled:
            try:
                compiled.append((rule.target, re.compile(rule.pattern, re.IGNORECASE)))
            except re.error as exc:
                raise ValueError(f"过滤正则无效：{rule.name}: {exc}") from exc
    # 路径组件树同时传播父目录命中和累计子树大小，无目录两两比较。
    tree = {"children": {}, "item": None}
    for index, item in enumerate(items):
        if index % 256 == 0:
            checkpoint()
        node = tree
        for part in item['relative_path'].split('/'):
            node = node['children'].setdefault(os.path.normcase(part), {"children": {}, "item": None})
        node['item'] = item
    directories, files = [], []
    stack = [(tree, False, False)]
    while stack:
        node, parent_selected, visited = stack.pop()
        if not visited:
            checkpoint()
            item = node['item']
            selected = False
            if item is not None:
                kind = 'folder' if item['type'] == 'dir' else 'file'
                match = (kind != 'folder' or filter_dirs) and any(
                    target in (kind, 'all') and regex.search(item['name']) for target, regex in compiled)
                selected = bool(match and not parent_selected)
                if selected:
                    (directories if kind == 'folder' else files).append(item)
            node['selected'] = selected
            stack.append((node, parent_selected, True))
            stack.extend((child, parent_selected or selected, False) for child in node['children'].values())
        else:
            item = node['item']
            node['size'] = sum(child['size'] for child in node['children'].values())
            if item is not None and item['type'] == 'file':
                node['size'] += item['size']
            elif item is not None and node['selected']:
                item['size'] = node['size']
    return directories, files
