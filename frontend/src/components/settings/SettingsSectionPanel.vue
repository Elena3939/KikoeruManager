<template>
  <section class="settings-section-panel">
    <header class="panel-header">
      <div>
        <p class="panel-kicker">{{ kicker }}</p>
        <h2 class="panel-title">{{ title }}</h2>
        <p v-if="description" class="panel-desc">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="panel-actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="panel-body">
      <slot />
    </div>
  </section>
</template>

<script setup>
defineProps({
  kicker: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, default: '' }
})
</script>

<style scoped>
/* Flat 风：不再是一个独立的大白卡浮窗，直接铺在 settings-page 白底上
   避免“卡里装内容必须滚动”的下拉浮窗视觉错觉 */
.settings-section-panel {
  min-width: 0;
  max-width: 100%;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  overflow: visible;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  padding: 0;
  background: transparent;
  border-bottom: none;
}

.panel-kicker {
  margin: 0 0 6px;
  color: var(--set-text-subtle, #94a3b8);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.panel-title {
  margin: 0;
  color: var(--set-text-strong, #1d1d1f);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.3px;
}

.panel-desc {
  margin: 6px 0 0;
  max-width: 720px;
  color: var(--set-text-muted, rgba(29, 29, 31, 0.6));
  font-size: 13px;
  line-height: 1.65;
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 28px;
  min-width: 0;
  max-width: 100%;
  padding: 0 0 22px;
}

.panel-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

@media (max-width: 960px) {
  .panel-header {
    flex-direction: column;
    margin-bottom: 12px;
  }

  .panel-body {
    padding: 0 0 18px;
  }
}
</style>
