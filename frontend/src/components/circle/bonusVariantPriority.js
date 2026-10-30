const BONUS_LANGUAGE_PRIORITY = {
  simplified: 0,
  traditional: 1,
  original: 2,
}

export function sortBonusVariants(members, getCoverPriority) {
  const languages = new Set(
    members
      .map(member => member?.preferred_variant?.group_key)
      .filter(group => Object.hasOwn(BONUS_LANGUAGE_PRIORITY, group)),
  )
  const hasLanguageVariants = languages.size > 1

  return members
    .map((member, index) => ({
      member,
      index,
      languagePriority: BONUS_LANGUAGE_PRIORITY[member?.preferred_variant?.group_key] ?? 3,
      coverPriority: getCoverPriority(member),
    }))
    .sort((a, b) => (
      (hasLanguageVariants ? a.languagePriority - b.languagePriority : 0)
      || b.coverPriority - a.coverPriority
      || a.index - b.index
    ))
    .map(entry => entry.member)
}
