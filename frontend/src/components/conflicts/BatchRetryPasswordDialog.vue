<template>
  <Teleport to="body">
    <Transition name="brp-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-[4000] flex items-center justify-center p-4 bg-black/20 backdrop-blur-[1.5px]"
        @click.self="handleCancel"
      >
        <div class="brp-shell relative w-full max-w-[540px] max-h-[calc(100vh-2rem)] flex flex-col">
          <div class="relative overflow-hidden rounded-[26px] bg-white/98 border border-slate-100 shadow-2xl shadow-slate-900/10 flex flex-col max-h-[calc(100vh-2rem)]">
            <!-- Head -->
            <div class="flex items-start gap-3.5 px-6 pt-6 flex-none">
              <div class="w-11 h-11 flex-shrink-0 flex items-center justify-center rounded-2xl border bg-amber-50/92 text-amber-700 border-amber-200/48">
                <RotateCcw :size="20" />
              </div>
              <div class="flex-1 min-w-0 pt-0.5">
                <h3 class="text-xl font-bold leading-tight text-slate-900">批量重试</h3>
                <p class="mt-1.5 text-slate-500 text-[13px] leading-relaxed">
                  为以下 {{ conflicts.length }} 个问题项分别指定密码（可选）。留空则按原逻辑走密码库和默认密码。
                </p>
              </div>
              <button
                type="button"
                class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 hover:rotate-90 transition-all duration-200"
                @click="handleCancel"
              >
                <X :size="18" />
              </button>
            </div>

            <!-- List -->
            <div class="flex-1 min-h-0 overflow-y-auto px-6 py-4">
              <div class="flex flex-col gap-2.5">
                <div
                  v-for="item in items"
                  :key="item.id"
                  class="flex items-center gap-3 p-3 rounded-2xl bg-slate-50 border border-slate-200/80 hover:border-slate-300/80 transition-colors duration-150"
                >
                  <div class="flex-1 min-w-0">
                    <div class="font-medium text-slate-800 text-sm truncate">{{ item.label }}</div>
                    <div v-if="item.conflictType" class="text-xs text-slate-400 mt-0.5">{{ item.conflictType }}</div>
                  </div>
                  <input
                    v-model="item.password"
                    type="text"
                    class="w-44 flex-shrink-0 px-3 py-1.5 rounded-xl bg-white border border-slate-200 text-slate-800 placeholder-slate-400 text-sm outline-none transition-all duration-200 focus:border-blue-400/60 focus:ring-2 focus:ring-blue-100/50"
                    placeholder="密码（可留空）"
                    @keydown.enter.prevent="handleConfirm"
                    @keydown.stop
                  />
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex-none flex items-center justify-between gap-3 px-6 pb-6 pt-3 border-t border-slate-100">
              <p class="text-xs text-slate-400">已指定密码 {{ specifiedCount }} / {{ conflicts.length }} 项</p>
              <div class="flex items-center gap-2.5">
                <button
                  type="button"
                  class="px-4 py-1.5 text-sm text-slate-500 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-all duration-150 font-medium"
                  @click="handleCancel"
                >
                  取消
                </button>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 justify-center px-5 py-2.5 rounded-xl font-semibold text-[14px] text-white bg-amber-500 hover:bg-amber-600 transition-all duration-150 active:scale-95"
                  @click="handleConfirm"
                >
                  <RotateCcw :size="14" />
                  开始批量重试 ({{ conflicts.length }})
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RotateCcw, X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  conflicts: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed(() => props.modelValue)

const items = ref([])

watch(() => props.conflicts, (list) => {
  items.value = list.map(c => ({
    id: c.id,
    label: c.rjcode || c.new_metadata?.work_name || c.new_path || '未识别问题项',
    conflictType: conflictTypeLabel(c.conflict_type),
    password: ''
  }))
}, { immediate: true })

const specifiedCount = computed(() => items.value.filter(i => i.password.trim()).length)

function conflictTypeLabel(type) {
  return {
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败',
    DUPLICATE: '完全重复',
    LANGUAGE_VARIANT: '多语言版本',
    MULTIPLE_VERSIONS: '多版本冲突',
    LINKED_WORK: '关联作品'
  }[type] || type || ''
}

function handleConfirm() {
  emit('confirm', items.value.map(i => ({ conflictId: i.id, password: i.password.trim() })))
  emit('update:modelValue', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:modelValue', false)
}
</script>

<style scoped>
.brp-fade-enter-active, .brp-fade-leave-active { transition: opacity 0.22s ease; }
.brp-fade-enter-active .brp-shell, .brp-fade-leave-active .brp-shell { transition: transform 0.24s ease, opacity 0.24s ease, filter 0.24s ease; }
.brp-fade-enter-from, .brp-fade-leave-to { opacity: 0; }
.brp-fade-enter-from .brp-shell, .brp-fade-leave-to .brp-shell { transform: translateY(6px) scale(0.985); opacity: 0; filter: blur(1px); }
</style>
