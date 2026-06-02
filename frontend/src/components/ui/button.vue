<template>
  <component
    :is="as"
    :class="buttonClasses"
    :disabled="as === 'button' ? disabled : undefined"
    v-bind="$attrs"
  >
    <slot />
  </component>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'

type ButtonVariant = 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon'

const props = withDefaults(defineProps<{
  as?: string
  variant?: ButtonVariant
  size?: ButtonSize
  disabled?: boolean
  class?: unknown
}>(), {
  as: 'button',
  variant: 'default',
  size: 'default',
  disabled: false,
})

defineOptions({
  inheritAttrs: false,
})

const variantClasses: Record<ButtonVariant, string> = {
  default: 'bg-slate-950 text-white shadow-sm hover:bg-slate-800 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200',
  destructive: 'bg-rose-600 text-white shadow-sm hover:bg-rose-700 dark:bg-rose-500 dark:hover:bg-rose-400',
  outline: 'border border-slate-200 bg-white text-slate-950 shadow-sm hover:bg-slate-100 hover:text-slate-950 dark:border-white/12 dark:bg-slate-950 dark:text-slate-50 dark:hover:bg-white/10',
  secondary: 'bg-slate-100 text-slate-950 shadow-sm hover:bg-slate-200 dark:bg-white/10 dark:text-slate-50 dark:hover:bg-white/15',
  ghost: 'text-slate-700 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-200 dark:hover:bg-white/10 dark:hover:text-white',
  link: 'text-slate-950 underline-offset-4 hover:underline dark:text-slate-50',
}

const sizeClasses: Record<ButtonSize, string> = {
  default: 'h-9 px-4 py-2',
  sm: 'h-8 rounded-md px-3 text-xs',
  lg: 'h-10 rounded-md px-8',
  icon: 'h-9 w-9',
}

const buttonClasses = computed(() =>
  cn(
    'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium tracking-normal outline-none transition-[transform,background-color,border-color,color,box-shadow,opacity] duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] active:scale-[0.96] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 hover:[&_svg]:-rotate-6 hover:[&_svg]:scale-110',
    variantClasses[props.variant],
    sizeClasses[props.size],
    props.class
  )
)
</script>
