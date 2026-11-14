import jschardet from 'jschardet'

export const TEXT_ENCODING_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'utf-8', label: 'UTF-8 / UTF-8 BOM' },
  { value: 'shift_jis', label: 'Shift-JIS / CP932（日文）' },
  { value: 'euc-jp', label: 'EUC-JP（日文）' },
  { value: 'iso-2022-jp', label: 'ISO-2022-JP（日文）' },
  { value: 'gb18030', label: 'GB18030 / GBK（中文）' },
  { value: 'big5', label: 'Big5（繁体中文）' },
  { value: 'utf-16le', label: 'UTF-16 LE' },
  { value: 'utf-16be', label: 'UTF-16 BE' },
  { value: 'euc-kr', label: 'EUC-KR（韩文）' },
  { value: 'windows-1252', label: 'Windows-1252（西欧）' },
]

export function normalizeTextEncoding (encoding) {
  const label = String(encoding || '').toLowerCase().replaceAll('_', '-')
  const aliases = {
    ascii: 'utf-8', 'utf-8-sig': 'utf-8', utf8: 'utf-8',
    'shift-jis': 'shift_jis', sjis: 'shift_jis', cp932: 'shift_jis',
    gb2312: 'gb18030', gbk: 'gb18030',
    'utf-16': 'utf-16le', 'utf-16-le': 'utf-16le', 'utf-16-be': 'utf-16be',
  }
  return new TextDecoder(aliases[label] || label).encoding
}

export function detectTextEncoding (bytes) {
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return { encoding: 'utf-8', confidence: 1, source: 'BOM' }
  }
  if (bytes[0] === 0xff && bytes[1] === 0xfe) {
    return { encoding: 'utf-16le', confidence: 1, source: 'BOM' }
  }
  if (bytes[0] === 0xfe && bytes[1] === 0xff) {
    return { encoding: 'utf-16be', confidence: 1, source: 'BOM' }
  }
  // 无 BOM 的 UTF-16 可能也是合法 ASCII 字节，含 NUL 时交给检测器判断。
  const sample = bytes.subarray(0, 64 * 1024)
  if (!sample.includes(0) && !sample.includes(0x1b)) {
    try {
      new TextDecoder('utf-8', { fatal: true }).decode(bytes)
      return { encoding: 'utf-8', confidence: 1, source: 'UTF-8 校验' }
    } catch { /* 非 UTF-8 文本继续执行统计识别。 */ }
  }
  let binary = ''
  for (let offset = 0; offset < sample.length; offset += 8192) {
    binary += String.fromCharCode(...sample.subarray(offset, offset + 8192))
  }
  const result = jschardet.detect(binary, { minimumThreshold: 0 })
  if (!result.encoding) throw new Error('未能识别文本编码，请手动选择编码')
  return {
    encoding: normalizeTextEncoding(result.encoding),
    confidence: result.confidence,
    source: 'jschardet',
  }
}

export function decodeTextBytes (bytes, encoding) {
  return new TextDecoder(normalizeTextEncoding(encoding)).decode(bytes)
}
