<template>
  <li class="nav-item">
    <div
      class="nav-row"
      :class="{ 'nav-row-active': isActive }"
      :style="{ paddingLeft: `${depth * 14 + 12}px` }"
      :title="node.path"
      @click="emit('navigate', node.path)"
    >
      <button
        type="button"
        class="nav-expander"
        :disabled="loading || submitting"
        @click.stop="emit('toggle', { libraryId, path: node.path })"
      >
        <ChevronDown
          v-if="state.expanded"
          :size="13"
          :stroke-width="2.2"
          class="text-slate-400"
        />
        <ChevronRight
          v-else
          :size="13"
          :stroke-width="2.2"
          class="text-slate-400"
        />
      </button>
      <Folder :size="13" :stroke-width="2.2" class="nav-folder-icon" />
      <span class="nav-row-name">{{ node.name }}</span>
    </div>

    <ul v-if="state.expanded" class="nav-children">
      <li
        v-if="state.loading"
        class="nav-row-meta"
        :style="{ paddingLeft: `${(depth + 1) * 14 + 12 + 6}px` }"
      >
        <Loader2 :size="12" :stroke-width="2.2" class="animate-spin text-slate-400" />
        <span>加载中...</span>
      </li>
      <li
        v-else-if="state.error"
        class="nav-row-meta nav-row-meta-error"
        :style="{ paddingLeft: `${(depth + 1) * 14 + 12 + 6}px` }"
      >
        {{ state.error }}
      </li>
      <template v-else>
        <LibraryMoveNavNode
          v-for="child in (state.children || [])"
          :key="child.path"
          :node="child"
          :depth="depth + 1"
          :library-id="libraryId"
          :tree-state="treeState"
          :current-path="currentPath"
          :current-library-id="currentLibraryId"
          :loading="loading"
          :submitting="submitting"
          @navigate="value => emit('navigate', value)"
          @toggle="value => emit('toggle', value)"
        />
        <li
          v-if="state.children && !state.children.length"
          class="nav-row-meta"
          :style="{ paddingLeft: `${(depth + 1) * 14 + 12 + 6}px` }"
        >
          <span>（空）</span>
        </li>
      </template>
    </ul>
  </li>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronDown, ChevronRight, Folder, Loader2 } from 'lucide-vue-next'

defineOptions({ name: 'LibraryMoveNavNode' })

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 1 },
  libraryId: { type: String, required: true },
  treeState: { type: Object, required: true },
  currentPath: { type: String, default: '' },
  currentLibraryId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false }
})

const emit = defineEmits(['navigate', 'toggle'])

const state = computed(() => {
  const libState = props.treeState?.[props.libraryId]
  const nodes = libState?.nodes || {}
  return nodes[props.node.path] || { expanded: false, children: null, loading: false, error: '' }
})

const isActive = computed(() => {
  if (props.libraryId !== props.currentLibraryId) return false
  return normalizePath(props.node.path) === normalizePath(props.currentPath)
})

function normalizePath (path) {
  return String(path || '').replace(/[\\/]+$/, '').toLowerCase()
}
</script>

<style scoped>
.nav-item { list-style: none; }

.nav-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 0;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  color: #1e293b;
  border-radius: 6px;
  transition: background-color 0.15s ease;
}

.nav-row:hover { background: rgba(15, 23, 42, 0.05); }

.nav-row-active {
  background: rgba(186, 230, 253, 0.55);
  color: #0c4a6e;
  font-weight: 600;
}

.nav-row-active:hover { background: rgba(186, 230, 253, 0.7); }

.nav-expander {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
  transition: background-color 0.15s ease;
}

.nav-expander:hover:not(:disabled) { background: rgba(15, 23, 42, 0.08); }

.nav-expander:disabled { opacity: 0.4; cursor: not-allowed; }

.nav-folder-icon {
  color: #f59e0b;
  fill: currentColor;
  stroke: currentColor;
  flex-shrink: 0;
}

.nav-row-active .nav-folder-icon { color: #d97706; }

.nav-row-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-children {
  list-style: none;
  margin: 0;
  padding: 0;
}

.nav-row-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px 4px 0;
  font-size: 11.5px;
  color: #94a3b8;
  font-style: italic;
  user-select: none;
}

.nav-row-meta-error { color: #b91c1c; font-style: normal; }
</style>
