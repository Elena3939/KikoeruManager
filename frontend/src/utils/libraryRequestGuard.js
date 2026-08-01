export function normalizeSuccessfulDeletePaths (result) {
  return (Array.isArray(result?.success_paths) ? result.success_paths : [])
    .map(item => typeof item === 'string' ? item : item?.path)
    .map(path => String(path || '').trim())
    .filter(Boolean)
}

export function createLatestRequestGate () {
  let epoch = 0
  let controller = null
  let discardedResponses = 0

  return {
    begin () {
      epoch += 1
      controller?.abort()
      controller = new AbortController()
      return { epoch, controller }
    },
    invalidate () {
      epoch += 1
      controller?.abort()
      controller = null
      return epoch
    },
    isCurrent (request) {
      const current = Boolean(
        request &&
        request.epoch === epoch &&
        request.controller === controller &&
        !request.controller.signal.aborted
      )
      if (!current && request) discardedResponses += 1
      return current
    },
    finish (request) {
      if (!this.isCurrent(request)) return false
      controller = null
      return true
    },
    currentEpoch () {
      return epoch
    },
    diagnostics () {
      return { epoch, discardedResponses, requestInFlight: controller !== null }
    },
  }
}
