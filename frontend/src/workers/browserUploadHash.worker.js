import { sha256 } from '../utils/uploadSha256.js'

self.onmessage = async ({ data: { id, buffer } }) => {
  try {
    const digest = self.crypto?.subtle
      ? Array.from(new Uint8Array(await self.crypto.subtle.digest('SHA-256', buffer)), value => value.toString(16).padStart(2, '0')).join('')
      : sha256(buffer)
    self.postMessage({ id, digest, buffer }, [buffer])
  } catch (error) {
    self.postMessage({ id, error: error.message })
  }
}
