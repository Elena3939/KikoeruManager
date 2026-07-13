function normalizeRjcode(value) {
  return String(value || '').trim().toUpperCase()
}

function itemCode(item) {
  return normalizeRjcode(item?.canonical_rjcode || item?.display_rjcode || item?.rjcode)
}

function isOwned(item) {
  return Boolean(item?.owned || item?.server_owned || item?.completion_owned || item?.local_owned)
}

function patchOwnedState(item, refreshed) {
  const owned = Boolean(refreshed?.local_owned || refreshed?.has_kikoeru)
  return {
    ...item,
    owned,
    server_owned: owned,
    completion_owned: owned,
    local_owned: owned,
    has_kikoeru: owned,
    server_match_rjcodes: Array.isArray(refreshed?.server_match_rjcodes)
      ? [...refreshed.server_match_rjcodes]
      : (item?.server_match_rjcodes || []),
    server_match_primary_rjcode: String(
      refreshed?.server_match_primary_rjcode || item?.server_match_primary_rjcode || '',
    ),
    subtitle_present: Boolean(refreshed?.subtitle_present ?? item?.subtitle_present),
    local_subtitle_present: Boolean(refreshed?.local_subtitle_present ?? item?.local_subtitle_present),
    local_folder_size: Number(refreshed?.local_folder_size ?? item?.local_folder_size ?? 0),
    local_file_count: Number(refreshed?.local_file_count ?? item?.local_file_count ?? 0),
    subtitle_file_count: Number(refreshed?.subtitle_file_count ?? item?.subtitle_file_count ?? 0),
    subtitle_dir: String(refreshed?.subtitle_dir ?? item?.subtitle_dir ?? ''),
  }
}

export function reconcileCircleCompletionOwnedState(items, refreshedItems, tab) {
  const refreshedByCode = new Map(
    (Array.isArray(refreshedItems) ? refreshedItems : [])
      .map(item => [itemCode(item), item])
      .filter(([code]) => code),
  )
  if (!refreshedByCode.size) {
    return { items: Array.isArray(items) ? items : [], gainedCodes: [], lostCodes: [] }
  }

  const gainedCodes = new Set()
  const lostCodes = new Set()
  const reconciled = (Array.isArray(items) ? items : []).map(item => {
    const members = [item, ...(Array.isArray(item?.bonus_works) ? item.bonus_works : [])]
    const patchedMembers = members.map(member => {
      const code = itemCode(member)
      const refreshed = refreshedByCode.get(code)
      if (!refreshed) return member
      const beforeOwned = isOwned(member)
      const patched = patchOwnedState(member, refreshed)
      if (!beforeOwned && isOwned(patched)) gainedCodes.add(code)
      if (beforeOwned && !isOwned(patched)) lostCodes.add(code)
      return patched
    })
    const [patchedItem, ...patchedBonuses] = patchedMembers
    return {
      ...patchedItem,
      ...(Array.isArray(item?.bonus_works) ? { bonus_works: patchedBonuses } : {}),
    }
  })

  const tabKey = String(tab || '').trim().toLowerCase()
  const filtered = reconciled.filter(item => {
    const members = [item, ...(Array.isArray(item?.bonus_works) ? item.bonus_works : [])]
    const groupOwned = members.some(isOwned)
    if (tabKey === 'missing') return !groupOwned
    if (tabKey === 'owned') return groupOwned
    return true
  })

  return {
    items: filtered,
    gainedCodes: [...gainedCodes],
    lostCodes: [...lostCodes],
  }
}
