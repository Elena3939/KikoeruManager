// 规则只识别相同标题；跨语言含义交给 AI，轨号不单独构成高置信依据。
export function buildSubtitleRuleCandidates(audioList, subtitleList, normalizeName, stripAudioExtension) {
  const pairs = []
  const usedAudio = new Set()
  const usedSubtitle = new Set()
  const base = name => stripAudioExtension(String(name || '').replace(/\.[^.]+$/, '')).toLowerCase()
  const groupBy = (items, keyOf) => {
    const groups = new Map()
    for (const item of items) {
      const key = keyOf(item.name)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(item)
    }
    return groups
  }
  for (const [keyOf, confidenceLevel, matchReason] of [
    [base, 'high', '精确文件名'],
    [normalizeName, 'medium', '规范化标题']
  ]) {
    const audioByKey = groupBy(audioList, keyOf)
    const subtitleByKey = groupBy(subtitleList, keyOf)
    for (const [key, audios] of audioByKey) {
      const subtitles = subtitleByKey.get(key) || []
      if (!key || audios.length !== 1 || subtitles.length !== 1) continue
      const audio = audios[0]
      const subtitle = subtitles[0]
      if (usedAudio.has(audio.path) || usedSubtitle.has(subtitle.path)) continue
      usedAudio.add(audio.path)
      usedSubtitle.add(subtitle.path)
      pairs.push({ audio, subtitle, confidenceLevel, matchReason })
    }
  }
  return pairs
}
