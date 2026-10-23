"""社团分页共享的展示模型；标题比较仅在服务端选择缓存未命中时执行。"""
import re
from functools import lru_cache


def bonus_title(item):
    title = str(item.get('_bonus_display_title') or item.get('title') or '').strip()
    return re.sub(r'[_＿]\s*[0-9０-９]+\s*$', '', title).strip()


@lru_cache(maxsize=4096)
def _bonus_title_groups(signature):
    """只缓存编号、标题和成员下标，资源/收录状态始终取当前覆盖层。"""
    titles = [re.sub(r'[\s　]+', ' ', title) for code, title in signature]
    themes = {}
    for title in titles:
        match = re.search(r'(\d+)\s*大特典', title)
        if match:
            key = match.group(1)
            themes[key] = min(themes.get(key, len(title)), len(title))
    buckets, seen = {}, set()
    for index, (code, raw_title) in enumerate(signature):
        if code in seen:
            continue
        seen.add(code)
        title = titles[index]
        match = re.search(r'(\d+)\s*大特典', title)
        if '特典' in title and ((match and themes[match.group(1)] < len(title)) or any(
                other and len(other) < len(title) and other in title
                and (re.fullmatch(r'【[^】]+】', other) or '】' not in other)
                for other in titles)):
            continue
        key = raw_title or code
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(index)
    return tuple((key, tuple(indices)) for key, indices in buckets.items())


def present_bonus_works(service, bonuses):
    candidates = service._completion_select_bonus_variants([
        item for item in bonuses if item.get('is_bonus_work')
        and not service._completion_is_bonus_without_cover(item)])
    signature = tuple((item.get('display_rjcode') or item.get('canonical_rjcode'), bonus_title(item))
                      for item in candidates)
    result = []
    for title, indices in _bonus_title_groups(signature):
        members = [candidates[index] for index in indices]
        bucket = {**members[0], '_bonus_display_title': title, '_bonus_members': members}
        bucket['bonus_owned_label'] = '已收录' if any(item.get('owned') or item.get('server_owned')
            or item.get('completion_owned') or item.get('local_owned') for item in members) else '未收录'
        bucket['bonus_download_label'] = '可下载' if any(item.get('local_download_ready')
            or item.get('has_downloadable_source', item.get('has_asmr_one')) for item in members) else '无源'
        result.append(bucket)
    return result


def present_completion_rows(service, rows):
    for row in rows:
        row['bonus_display_works'] = present_bonus_works(service, row.get('bonus_works') or [])
    return rows
