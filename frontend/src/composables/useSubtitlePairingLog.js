import { computed, ref, watch } from 'vue'

// 每个工作台保留当前目录的配对过程，避免切任务后混入旧日志。
export function useSubtitlePairingLog(contextKey) {
  const entries = ref([])
  const aiDiagnostics = ref(null)
  watch(contextKey, () => { entries.value = []; aiDiagnostics.value = null }, { flush: 'sync' })
  function logPairing(message, level = 'info') {
    entries.value = [...entries.value.slice(-199), { time: new Date().toISOString(), level, message }]
  }
  function capturePairingAudit(pairs, mode) {
    return {
      pairingMode: mode || '',
      aiDiagnostics: ['ai', 'manual'].includes(mode) ? aiDiagnostics.value : null,
      pairChanges: pairs.map(pair => ({
        audio_before: pair.audio_name || '', audio_after: pair.target_audio_name || '',
        subtitle_before: pair.subtitle_name || '', subtitle_after: pair.target_subtitle_name || '',
        reason: pair.matchReason || '', confidence: pair.confidenceLevel || ''
      }))
    }
  }
  return { pairingLogs: computed(() => entries.value), logPairing, aiDiagnostics, capturePairingAudit }
}
