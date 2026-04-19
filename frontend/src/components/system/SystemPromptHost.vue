<template>
  <Teleport to="body">
    <Transition name="system-prompt-fade">
      <SystemPromptDialog
        v-if="currentPrompt"
        :prompt="currentPrompt"
        @confirm="handleConfirm"
        @cancel="handleCancel"
        @close="handleClose"
      />
    </Transition>
  </Teleport>
</template>

<script setup>
import { onBeforeUnmount, onMounted, watch } from 'vue'
import SystemPromptDialog from './SystemPromptDialog.vue'
import { useSystemPromptHost } from '../../composables/useSystemPrompt'

const {
  currentPrompt,
  hasPrompt,
  resolveSystemPrompt,
  rejectSystemPrompt,
  cancelReason,
  closeReason
} = useSystemPromptHost()

watch(
  hasPrompt,
  value => {
    document.body.classList.toggle('system-prompt-open', value)
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.body.classList.remove('system-prompt-open')
  window.removeEventListener('keydown', handleKeydown)
})

function handleConfirm(payload) {
  resolveSystemPrompt(payload)
}

function handleCancel() {
  rejectSystemPrompt(cancelReason)
}

function handleClose() {
  rejectSystemPrompt(closeReason)
}

function handleKeydown(event) {
  if (event.key !== 'Escape' || !currentPrompt.value?.options) return
  if (currentPrompt.value.options.closeOnPressEscape === false) return
  event.preventDefault()
  rejectSystemPrompt(closeReason)
}
</script>
