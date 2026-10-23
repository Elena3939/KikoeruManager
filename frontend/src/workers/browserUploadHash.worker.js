import { sha256 } from '../utils/uploadSha256.js'

self.onmessage = ({ data: { id, buffer } }) => {
  try {
    self.postMessage({ id, digest: sha256(buffer), buffer }, [buffer])
  } catch (error) {
    self.postMessage({ id, error: error.message })
  }
}
