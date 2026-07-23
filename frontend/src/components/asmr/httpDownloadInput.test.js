import { describe, expect, it } from 'vitest'

import {
  isPikPakPassCodeLine,
  normalizeHttpDownloadInputRows,
  normalizePikPakShareText,
  pikPakShareIdentity,
} from './httpDownloadInput.js'

describe('PikPak 下载输入', () => {
  it('把下一行提取码合并到对应分享链接', () => {
    expect(normalizeHttpDownloadInputRows([
      'https://mypikpak.com/s/share-a',
      '提取码：A1b2',
      'https://example.com/file.zip',
    ])).toEqual([
      'https://mypikpak.com/s/share-a?pwd=A1b2',
      'https://example.com/file.zip',
    ])
  })

  it('从完整分享文案中提取链接和密码', () => {
    expect(normalizePikPakShareText(
      '分享给你：https://drive.mypikpak.com/s/share-b 访问码: 9z8y',
    )).toBe('https://drive.mypikpak.com/s/share-b?pwd=9z8y')
  })

  it('身份比较忽略提取码并能识别独立密码行', () => {
    expect(pikPakShareIdentity('https://mypikpak.com/s/share-c?pwd=abcd'))
      .toBe(pikPakShareIdentity('https://mypikpak.com/s/share-c'))
    expect(isPikPakPassCodeLine('密码：abcd')).toBe(true)
    expect(isPikPakPassCodeLine('https://mypikpak.com/s/share-c')).toBe(false)
  })
})
