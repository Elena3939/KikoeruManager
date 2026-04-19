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
.settings-section-panel {
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 26px 28px 18px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(255, 255, 255, 0.98));
  border-bottom: 1px solid rgba(226, 232, 240, 0.82);
}

.panel-kicker {
  margin: 0 0 8px;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.panel-title {
  margin: 0;
  color: #0f172a;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.05;
}

.panel-desc {
  margin: 10px 0 0;
  max-width: 720px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.7;
}

.panel-body {
  padding: 24px 28px 28px;
}

.panel-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

@media (max-width: 960px) {
  .panel-header {
    flex-direction: column;
  }

  .panel-body {
    padding: 20px;
  }
}
</style>
