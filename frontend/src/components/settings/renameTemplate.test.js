import { describe, expect, it } from 'vitest'
import {
  parseRenameTemplate,
  parseRenameTemplateForBuilder,
  serializeRenameTemplate,
} from './renameTemplate'

describe('renameTemplate', () => {
  it('把旧社团变量迁移为原社团变量', () => {
    const blocks = parseRenameTemplate('[{maker_name}][{rjcode}]')

    expect(blocks[1]).toEqual({
      type: 'variable',
      value: 'original_maker_name',
      token: '{maker_name}',
    })
    expect(serializeRenameTemplate(blocks)).toBe(
      '[{original_maker_name}][{rjcode}]',
    )
  })

  it('把统一字段括号从可拖动块中剥离并无损还原', () => {
    const wrapper = {
      wrapperEnabled: true,
      wrapperLeft: '[',
      wrapperRight: ']',
    }
    const blocks = parseRenameTemplateForBuilder(
      '[{original_maker_name}][{rjcode}]-中文版',
      wrapper,
    )

    expect(blocks).toEqual([
      {
        type: 'variable',
        value: 'original_maker_name',
        token: '{original_maker_name}',
      },
      { type: 'variable', value: 'rjcode', token: '{rjcode}' },
      { type: 'text', value: '-中文版' },
    ])
    expect(serializeRenameTemplate(blocks, wrapper)).toBe(
      '[{original_maker_name}][{rjcode}]-中文版',
    )
  })

  it('支持关闭括号和自定义左右括号', () => {
    const blocks = parseRenameTemplate('{translator_name}{work_name}')

    expect(serializeRenameTemplate(blocks, {
      wrapperEnabled: true,
      wrapperLeft: '【',
      wrapperRight: '】',
    })).toBe('【{translator_name}】【{work_name}】')
    expect(serializeRenameTemplate(blocks)).toBe(
      '{translator_name}{work_name}',
    )
  })

  it('首次启用字段括号时移除旧默认变量间空格', () => {
    const wrapper = {
      wrapperEnabled: true,
      wrapperLeft: '[',
      wrapperRight: ']',
    }
    const blocks = parseRenameTemplateForBuilder(
      '{rjcode} {work_name}',
      wrapper,
    )

    expect(serializeRenameTemplate(blocks, wrapper)).toBe(
      '[{rjcode}][{work_name}]',
    )
  })

  it('把未知占位符保留为可编辑文本', () => {
    const template = '{rjcode}-{custom}-作品'

    expect(serializeRenameTemplate(parseRenameTemplate(template))).toBe(template)
  })

  it('允许变量重复并保留原顺序', () => {
    const template = '{rjcode}_{rjcode}'

    expect(serializeRenameTemplate(parseRenameTemplate(template))).toBe(template)
  })
})
