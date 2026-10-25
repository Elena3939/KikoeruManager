<template>
  <div class="subtitle-import-workbench">
    <section class="siw-shell" :aria-label="title">
      <header class="siw-header">
        <div class="siw-title-wrap">
          <div class="siw-brand" aria-hidden="true">
            <Captions class="siw-brand-icon" :stroke-width="2.15" />
          </div>
          <div class="siw-title-copy">
            <div class="siw-title-line">
              <h2>{{ title }}</h2>
              <span class="siw-live-pill"><span></span>Live</span>
            </div>
            <div class="siw-focus-row">
              <span class="siw-focus-code">{{ focusCode }}</span>
              <span class="siw-focus-name">{{ focusName }}</span>
            </div>
          </div>
        </div>

        <div class="siw-actions" aria-label="工作台操作">
          <slot name="actions" />
        </div>
      </header>
      <main class="siw-stage-wrap">
        <slot />
      </main>
    </section>
  </div>
</template>

<script setup>
import { Captions } from 'lucide-vue-next'

defineProps({
  title: { type: String, required: true },
  focusCode: { type: String, default: '等待任务' },
  focusName: { type: String, default: '' }
})
</script>

<style src="./subtitle-workbench-shell.css"></style>
