import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { compileStyle, parse } from '@vue/compiler-sfc'
import postcss from 'postcss'

const sourceDirectory = resolve(process.cwd(), 'src')

function readComponent(name) {
  return parse(readFileSync(`${sourceDirectory}/${name}`, 'utf8')).descriptor
}

function compile(style) {
  const result = compileStyle({
    source: style.content,
    scoped: Boolean(style.scoped),
    id: 'data-v-style-regression',
  })
  expect(result.errors).toEqual([])
  return postcss.parse(result.code)
}

describe('异步组件样式隔离', () => {
  it('项目样式不再接管外部 VoiceLinks 预览框', () => {
    for (const file of ['style.css', 'dark-mode.css']) {
      const stylesheet = postcss.parse(readFileSync(`${sourceDirectory}/${file}`, 'utf8'))
      const selectors = []
      stylesheet.walkRules(rule => {
        if (/voicelink-|_voicepopup/.test(rule.selector)) selectors.push(rule.selector)
      })
      expect(selectors).toEqual([])
    }
  })

  it('验证页不再使用通用玻璃卡片或向其它组件注入伪元素', () => {
    const descriptor = readComponent('views/VerifyGate.vue')
    expect(descriptor.template.content).toContain('gate-content')
    expect(descriptor.template.content).not.toContain('glass-card')
    for (const style of descriptor.styles) {
      compile(style).walkRules(rule => {
        expect(rule.selector).not.toContain('.glass-card')
      })
    }
  })

  it('所有组件编译后都不能给主题根节点附加布局或外观声明', () => {
    const violations = []
    const files = readdirSync(sourceDirectory, { recursive: true }).filter(name => name.endsWith('.vue'))
    for (const file of files) {
      for (const style of readComponent(file).styles.filter(style => style.scoped)) {
        compile(style).walkRules(rule => {
          if (!postcss.list.comma(rule.selector).some(selector =>
            /^(html|body)(\.(dark|kikoerumanager-dark))?$/.test(selector),
          )) return
          // 根节点仅允许声明主题色彩方案，组件的尺寸、颜色等必须指向具体目标。
          for (const declaration of rule.nodes.filter(node => node.type === 'decl')) {
            if (declaration.prop !== 'color-scheme') {
              violations.push(`${file}: ${rule.selector} { ${declaration.prop} }`)
            }
          }
        })
      }
    }
    expect(violations).toEqual([])
  })

  it('搜索浮层加载时保持页面边界，并将边框和内边距应用于目标输入框', () => {
    const descriptor = readComponent('components/library/LibrarySearchOverlay.vue')
    const rules = []
    for (const style of descriptor.styles) {
      compile(style).walkRules(rule => {
        if (postcss.list.comma(rule.selector).includes('html.kikoerumanager-dark .lib-panel-input[data-v-style-regression]')) {
          rules.push(rule.toString())
        }
      })
    }
    expect(rules.length).toBeGreaterThan(0)
    document.documentElement.classList.add('kikoerumanager-dark')
    const input = document.createElement('input')
    input.className = 'lib-panel-input'
    input.setAttribute('data-v-style-regression', '')
    const stylesheet = document.createElement('style')
    const rootLayout = () => {
      const style = getComputedStyle(document.documentElement)
      return [style.padding, style.borderWidth, style.margin, style.width]
    }
    const before = rootLayout()
    stylesheet.textContent = rules.join('\n')
    document.head.append(stylesheet)
    document.body.append(input)
    try {
      expect(rootLayout()).toEqual(before)
      expect(getComputedStyle(input).paddingLeft).toBe('8px')
      expect(getComputedStyle(input).borderTopWidth).toBe('1px')
    } finally {
      input.remove()
      stylesheet.remove()
      document.documentElement.classList.remove('kikoerumanager-dark')
    }
  })

  it('修正暗色规则后仍保留组件作用域，不影响其他页面的同名面板', () => {
    const selectors = []
    for (const style of readComponent('components/activity/ActivityDetailBody.vue').styles) {
      compile(style).walkRules(rule => {
        for (const selector of postcss.list.comma(rule.selector)) {
          if (selector.startsWith('html.kikoerumanager-dark .panel[')) selectors.push(selector)
        }
      })
    }
    expect(selectors).toContain('html.kikoerumanager-dark .panel[data-v-style-regression]')
    const panel = document.createElement('div')
    panel.className = 'panel'
    document.documentElement.classList.add('kikoerumanager-dark')
    document.body.append(panel)
    try {
      expect(selectors.some(selector => panel.matches(selector))).toBe(false)
      panel.setAttribute('data-v-style-regression', '')
      expect(selectors.some(selector => panel.matches(selector))).toBe(true)
    } finally {
      panel.remove()
      document.documentElement.classList.remove('kikoerumanager-dark')
    }
  })

  it('下载预览的样式仅匹配该弹窗、窗口和遮罩', () => {
    const violations = []
    const dialog = document.createElement('div')
    dialog.className = 'el-dialog custom-preview-modal circle-download-preview-modal'
    let responsiveDialogRules = 0
    for (const style of readComponent('components/circle/CircleDownloadPreviewDialog.vue').styles) {
      compile(style).walkRules(rule => {
        if (rule.parent.type === 'atrule' && /keyframes$/.test(rule.parent.name)) return
        if (rule.parent.name === 'media' && rule.selector.includes('.el-dialog')) {
          expect(dialog.matches(rule.selector)).toBe(true)
          responsiveDialogRules++
        }
        for (const selector of postcss.list.comma(rule.selector)) {
          if (!/\.circle-download-preview-(modal|overlay|window)\b/.test(selector)) {
            violations.push(selector)
          }
        }
      })
    }
    expect(violations).toEqual([])
    expect(responsiveDialogRules).toBeGreaterThan(0)
  })
})
