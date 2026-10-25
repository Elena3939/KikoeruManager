// 卡片、列表与库存定位共用展示版本，避免误用跨语言聚合的 canonical RJ。
export function circleWorkVersionRjcode(item) {
  return item?.owned
    ? (item.owned_variant?.rjcode || item.server_match_primary_rjcode || item.display_rjcode || item.canonical_rjcode || item.rjcode || '')
    : (item?.download_plan?.rjcode || item?.display_rjcode || item?.canonical_rjcode || item?.rjcode || '')
}
