// 模拟 frontend escapedSurrogateBytes + decodeEscapedSurrogateName，验证含 \udcXX 字面量的样本能否被解回真实文件名。
// 运行：node backend/scripts/regression_frontend_decode.js
'use strict'

// 这就是后端 sqlite_safe_text/_scrub_surrogates_for_json 出来的结果 ——
// 每个 \udcXX 是 6 个字面字符。这里用模板字符串中的 \\u 写法对应一个真实反斜杠 + u + 4 hex。
const sample = 'W\\udc83\\udc81\\udc83X\\udc83K\\udc83L\\udc83\\udc81\\udc83C\\udc83h\\udc81@\\udc91\\udc81\\udc8a\\udcfa\\udc8dw\\udc93\\udcfc\\udc93\\udcc1\\udc93T'

// 复刻 Conflicts.vue:1015 escapedSurrogateBytes
function escapedSurrogateBytes(value) {
  const text = String(value || '')
  const bytes = []
  let matched = false
  for (let i = 0; i < text.length;) {
    const literal = text.slice(i, i + 6)
    const literalMatch = /^\\udc([0-9a-fA-F]{2})$/.exec(literal)
    if (literalMatch) {
      bytes.push(parseInt(literalMatch[1], 16))
      matched = true
      i += 6
      continue
    }
    const code = text.charCodeAt(i)
    if (code >= 0xdc80 && code <= 0xdcff) {
      bytes.push(code - 0xdc00)
      matched = true
      i += 1
      continue
    }
    if (code <= 0xff) {
      bytes.push(code)
      i += 1
      continue
    }
    const encoded = new TextEncoder().encode(text[i])
    bytes.push(...encoded)
    i += 1
  }
  return matched ? new Uint8Array(bytes) : null
}

const bytes = escapedSurrogateBytes(sample)
console.log('sample length:', sample.length)
console.log('first 12 chars:', JSON.stringify(sample.slice(0, 12)))
console.log('matched bytes:', bytes && Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(' '))
if (bytes) {
  console.log('decode shift_jis ->', new TextDecoder('shift_jis', { fatal: false }).decode(bytes))
}
