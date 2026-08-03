export const RENAME_TEMPLATE_VARIABLES = [
  {
    value: 'original_maker_name',
    token: '{original_maker_name}',
    label: '原社团',
  },
  {
    value: 'translator_name',
    token: '{translator_name}',
    label: '翻译者',
  },
  { value: 'rjcode', token: '{rjcode}', label: 'RJ 号' },
  { value: 'work_name', token: '{work_name}', label: '作品名' },
  { value: 'maker_id', token: '{maker_id}', label: '原社团 ID' },
  { value: 'release_date', token: '{release_date}', label: '发售日期' },
  { value: 'cvs', token: '{cvs}', label: '声优' },
  { value: 'tags', token: '{tags}', label: '标签' },
]

const VARIABLE_ALIASES = [
  {
    value: 'original_maker_name',
    token: '{maker_name}',
  },
]

const VARIABLE_BY_TOKEN = new Map([
  ...RENAME_TEMPLATE_VARIABLES.map((variable) => [variable.token, variable]),
  ...VARIABLE_ALIASES.map((alias) => [alias.token, {
    ...getRenameTemplateVariable(alias.value),
    token: alias.token,
  }]),
])

const VARIABLE_PATTERN = new RegExp(
  `(${[...VARIABLE_BY_TOKEN.keys()]
    .map((token) => token.replace(/[{}]/g, '\\$&'))
    .join('|')})`,
  'g',
)

function normalizeWrapperOptions(options = {}) {
  return {
    enabled: Boolean(options.wrapperEnabled),
    left: String(options.wrapperLeft ?? ''),
    right: String(options.wrapperRight ?? ''),
  }
}

export function parseRenameTemplate(template) {
  return String(template ?? '')
    .split(VARIABLE_PATTERN)
    .filter((value) => value !== '')
    .map((value) => {
      const variable = VARIABLE_BY_TOKEN.get(value)
      if (variable) {
        return {
          type: 'variable',
          value: variable.value,
          token: value,
        }
      }
      return {
        type: 'text',
        value,
      }
    })
}

export function parseRenameTemplateForBuilder(template, options = {}) {
  const wrapper = normalizeWrapperOptions(options)
  const sourceTemplate = String(template ?? '')
  const blocks = parseRenameTemplate(template).map((block) => ({ ...block }))
  if (!wrapper.enabled || (!wrapper.left && !wrapper.right)) return blocks
  const hadWrappedVariable = RENAME_TEMPLATE_VARIABLES.some(
    (variable) => sourceTemplate.includes(
      `${wrapper.left}${variable.token}${wrapper.right}`,
    ),
  ) || VARIABLE_ALIASES.some(
    (alias) => sourceTemplate.includes(
      `${wrapper.left}${alias.token}${wrapper.right}`,
    ),
  )

  for (let index = 0; index < blocks.length; index += 1) {
    if (blocks[index]?.type !== 'variable') continue

    const previous = blocks[index - 1]
    const next = blocks[index + 1]
    const hasLeft = !wrapper.left
      || (previous?.type === 'text' && previous.value.endsWith(wrapper.left))
    const hasRight = !wrapper.right
      || (next?.type === 'text' && next.value.startsWith(wrapper.right))
    if (!hasLeft || !hasRight) continue

    if (wrapper.left) {
      previous.value = previous.value.slice(0, -wrapper.left.length)
    }
    if (wrapper.right) {
      next.value = next.value.slice(wrapper.right.length)
    }
  }

  return blocks.filter((block, index) => {
    if (block.type !== 'text' || block.value === '') return block.value !== ''
    if (hadWrappedVariable || block.value.trim() !== '') return true
    return !(
      blocks[index - 1]?.type === 'variable'
      && blocks[index + 1]?.type === 'variable'
    )
  })
}

export function serializeRenameTemplate(blocks, options = {}) {
  const wrapper = normalizeWrapperOptions(options)

  return (Array.isArray(blocks) ? blocks : [])
    .map((block) => {
      if (block?.type === 'variable') {
        const variable = getRenameTemplateVariable(block.value)
        if (!variable) return ''
        if (!wrapper.enabled) return variable.token
        return `${wrapper.left}${variable.token}${wrapper.right}`
      }
      return String(block?.value ?? '')
    })
    .join('')
}

export function getRenameTemplateVariable(value) {
  return RENAME_TEMPLATE_VARIABLES.find(
    (variable) => variable.value === value,
  ) || null
}
