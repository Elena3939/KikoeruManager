<template>
  <div class="min-h-screen bg-slate-50 p-6 text-slate-950 transition-colors dark:bg-slate-950 dark:text-slate-50">
    <div class="mx-auto flex max-w-3xl flex-col gap-6">
      <header class="flex items-center justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Magic UI Vue</p>
          <h1 class="mt-1 text-2xl font-semibold tracking-normal">Animated Theme Toggler</h1>
        </div>
        <AnimatedThemeToggler
          direction="ltr"
          transition-variant="circle"
          variant="outline"
          size="icon"
        />
      </header>

      <section class="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-white/5">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-sm font-semibold">当前主题</div>
            <div class="text-xs text-slate-500 dark:text-slate-400">
              {{ theme }} / {{ resolvedTheme }}
            </div>
          </div>
          <AnimatedThemeToggler
            direction="rtl"
            transition-variant="circle"
            variant="secondary"
            size="default"
            show-label
          />
        </div>

        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <AnimatedThemeToggler direction="ltr" transition-variant="rectangle" variant="outline" size="default" show-label />
          <AnimatedThemeToggler direction="rtl" transition-variant="rectangle" variant="outline" size="default" show-label />
          <AnimatedThemeToggler direction="ttb" transition-variant="rectangle" variant="outline" size="default" show-label />
          <AnimatedThemeToggler direction="btt" transition-variant="rectangle" variant="outline" size="default" show-label />
        </div>

        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <AnimatedThemeToggler transition-variant="circle" variant="ghost" size="icon" />
          <AnimatedThemeToggler transition-variant="diamond" variant="ghost" size="icon" />
          <AnimatedThemeToggler transition-variant="hexagon" variant="ghost" size="icon" />
          <AnimatedThemeToggler transition-variant="star" variant="ghost" size="icon" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import AnimatedThemeToggler from '@/components/magicui/AnimatedThemeToggler.vue'
import { useTheme } from '@/composables/useTheme'

const { theme, resolvedTheme } = useTheme()
</script>
