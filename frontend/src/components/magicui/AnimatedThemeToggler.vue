<template>
  <Button
    ref="buttonRef"
    type="button"
    :variant="variant"
    :size="size"
    :disabled="disabled || isAnimating"
    :class="buttonClasses"
    :aria-label="ariaLabel"
    :title="ariaLabel"
    @click="handleToggle"
  >
    <span class="animated-theme-toggler__icon-stack" aria-hidden="true">
      <Sun
        class="animated-theme-toggler__icon animated-theme-toggler__icon-sun"
        :class="{ 'is-visible': theme === 'dark' }"
        :size="iconSize"
        :stroke-width="2.35"
      />
      <Moon
        class="animated-theme-toggler__icon animated-theme-toggler__icon-moon"
        :class="{ 'is-visible': theme === 'light' }"
        :size="iconSize"
        :stroke-width="2.35"
      />
      <Monitor
        class="animated-theme-toggler__icon animated-theme-toggler__icon-system"
        :class="{ 'is-visible': theme === 'system' }"
        :size="iconSize"
        :stroke-width="2.35"
      />
    </span>
    <span v-if="showLabel" class="animated-theme-toggler__label">{{ label }}</span>
    <span class="sr-only">{{ label }}</span>
  </Button>
</template>

<script setup lang="ts">
import { computed, ref, unref } from 'vue'
import { Monitor, Moon, Sun } from 'lucide-vue-next'
import { cn } from '@/lib/utils'
import { useTheme, type ThemeMode } from '@/composables/useTheme'
import Button from '@/components/ui/button.vue'

type ButtonVariant = 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon'
type ThemeToggleDirection = 'ltr' | 'rtl' | 'ttb' | 'btt'
type TransitionVariant =
  | 'circle'
  | 'square'
  | 'triangle'
  | 'diamond'
  | 'hexagon'
  | 'rectangle'
  | 'star'

const props = withDefaults(defineProps<{
  direction?: ThemeToggleDirection
  duration?: number
  transitionVariant?: TransitionVariant
  fromCenter?: boolean
  disabled?: boolean
  size?: ButtonSize
  variant?: ButtonVariant
  showLabel?: boolean
  class?: unknown
}>(), {
  direction: 'ltr',
  duration: 400,
  transitionVariant: 'circle',
  fromCenter: false,
  disabled: false,
  size: 'icon',
  variant: 'ghost',
  showLabel: false,
})

const buttonRef = ref<InstanceType<typeof Button> | null>(null)
const isAnimating = ref(false)
const { theme, resolvedTheme, setTheme } = useTheme()

const iconSize = computed(() => (props.size === 'sm' ? 15 : props.size === 'lg' ? 20 : 17))
const label = computed(() => {
  const labels: Record<ThemeMode, string> = {
    light: '浅色模式',
    dark: '深色模式',
    system: `跟随系统：${resolvedTheme.value === 'dark' ? '深色' : '浅色'}`,
  }
  return labels[theme.value]
})
const ariaLabel = computed(() => `${label.value}，点击切换主题`)
const buttonClasses = computed(() =>
  cn(
    'animated-theme-toggler theme-toggle-button relative overflow-hidden',
    {
      'is-dark': resolvedTheme.value === 'dark',
      'is-system': theme.value === 'system',
      'is-animating': isAnimating.value,
    },
    props.class
  )
)

const overlayColors = {
  light: {
    background: '#f8fafc',
    glow: 'rgba(245, 158, 11, 0.24)',
    edge: 'rgba(251, 191, 36, 0.32)',
  },
  dark: {
    background: '#08090c',
    glow: 'rgba(96, 165, 250, 0.26)',
    edge: 'rgba(147, 197, 253, 0.28)',
  },
}

function polygonCollapsed(cx: number, cy: number, vertexCount: number) {
  return `polygon(${Array.from({ length: vertexCount }, () => `${cx}px ${cy}px`).join(', ')})`
}

function getDirectionalClipPaths(
  direction: ThemeToggleDirection,
  viewportWidth: number,
  viewportHeight: number
): [string, string] {
  switch (direction) {
    case 'rtl':
      return [
        `inset(0 0 0 ${viewportWidth}px)`,
        'inset(0 0 0 0)',
      ]
    case 'ttb':
      return [
        `inset(0 0 ${viewportHeight}px 0)`,
        'inset(0 0 0 0)',
      ]
    case 'btt':
      return [
        `inset(${viewportHeight}px 0 0 0)`,
        'inset(0 0 0 0)',
      ]
    case 'ltr':
    default:
      return [
        `inset(0 ${viewportWidth}px 0 0)`,
        'inset(0 0 0 0)',
      ]
  }
}

function getShapeClipPaths(
  variant: TransitionVariant,
  cx: number,
  cy: number,
  maxRadius: number,
  viewportWidth: number,
  viewportHeight: number
): [string, string] {
  switch (variant) {
    case 'circle':
      return [
        `circle(0px at ${cx}px ${cy}px)`,
        `circle(${maxRadius}px at ${cx}px ${cy}px)`,
      ]
    case 'square': {
      const halfSide = Math.max(
        Math.max(cx, viewportWidth - cx),
        Math.max(cy, viewportHeight - cy)
      ) * 1.05
      const end = [
        `${cx - halfSide}px ${cy - halfSide}px`,
        `${cx + halfSide}px ${cy - halfSide}px`,
        `${cx + halfSide}px ${cy + halfSide}px`,
        `${cx - halfSide}px ${cy + halfSide}px`,
      ].join(', ')
      return [polygonCollapsed(cx, cy, 4), `polygon(${end})`]
    }
    case 'triangle': {
      const scale = maxRadius * 2.2
      const dx = (Math.sqrt(3) / 2) * scale
      const verts = [
        `${cx}px ${cy - scale}px`,
        `${cx + dx}px ${cy + 0.5 * scale}px`,
        `${cx - dx}px ${cy + 0.5 * scale}px`,
      ].join(', ')
      return [polygonCollapsed(cx, cy, 3), `polygon(${verts})`]
    }
    case 'diamond': {
      const radius = maxRadius * Math.SQRT2
      const end = [
        `${cx}px ${cy - radius}px`,
        `${cx + radius}px ${cy}px`,
        `${cx}px ${cy + radius}px`,
        `${cx - radius}px ${cy}px`,
      ].join(', ')
      return [polygonCollapsed(cx, cy, 4), `polygon(${end})`]
    }
    case 'hexagon': {
      const radius = maxRadius * Math.SQRT2
      const verts: string[] = []
      for (let index = 0; index < 6; index += 1) {
        const angle = -Math.PI / 2 + (index * Math.PI) / 3
        verts.push(`${cx + radius * Math.cos(angle)}px ${cy + radius * Math.sin(angle)}px`)
      }
      return [polygonCollapsed(cx, cy, 6), `polygon(${verts.join(', ')})`]
    }
    case 'rectangle': {
      const halfW = Math.max(cx, viewportWidth - cx)
      const halfH = Math.max(cy, viewportHeight - cy)
      const end = [
        `${cx - halfW}px ${cy - halfH}px`,
        `${cx + halfW}px ${cy - halfH}px`,
        `${cx + halfW}px ${cy + halfH}px`,
        `${cx - halfW}px ${cy + halfH}px`,
      ].join(', ')
      return [polygonCollapsed(cx, cy, 4), `polygon(${end})`]
    }
    case 'star': {
      const radius = maxRadius * Math.SQRT2 * 1.03
      const innerRatio = 0.42
      const starPolygon = (currentRadius: number) => {
        const verts: string[] = []
        for (let index = 0; index < 5; index += 1) {
          const outerAngle = -Math.PI / 2 + (index * 2 * Math.PI) / 5
          const innerAngle = outerAngle + Math.PI / 5
          verts.push(`${cx + currentRadius * Math.cos(outerAngle)}px ${cy + currentRadius * Math.sin(outerAngle)}px`)
          verts.push(`${cx + currentRadius * innerRatio * Math.cos(innerAngle)}px ${cy + currentRadius * innerRatio * Math.sin(innerAngle)}px`)
        }
        return `polygon(${verts.join(', ')})`
      }
      return [starPolygon(Math.max(2, radius * 0.025)), starPolygon(radius)]
    }
    default:
      return [
        `circle(0px at ${cx}px ${cy}px)`,
        `circle(${maxRadius}px at ${cx}px ${cy}px)`,
      ]
  }
}

function getButtonElement() {
  const component = unref(buttonRef) as unknown as { $el?: HTMLElement } | HTMLElement | null
  if (!component) return null
  return '$el' in component ? component.$el : component
}

function getNextTheme(): ThemeMode {
  const systemResolvedTheme = getResolvedThemeForMode('system')
  if (theme.value === 'system') {
    return systemResolvedTheme === 'dark' ? 'light' : 'dark'
  }
  if (systemResolvedTheme === 'dark') {
    return theme.value === 'light' ? 'dark' : 'system'
  }
  return theme.value === 'dark' ? 'light' : 'system'
}

function getResolvedThemeForMode(nextTheme: ThemeMode) {
  if (nextTheme !== 'system') return nextTheme
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getTransitionOrigin(button: HTMLElement, viewportWidth: number, viewportHeight: number) {
  if (props.fromCenter) {
    return {
      x: viewportWidth / 2,
      y: viewportHeight / 2,
    }
  }
  const rect = button.getBoundingClientRect()
  const buttonX = rect.left + rect.width / 2
  const buttonY = rect.top + rect.height / 2

  switch (props.direction) {
    case 'rtl':
      return { x: viewportWidth, y: buttonY }
    case 'ttb':
      return { x: buttonX, y: 0 }
    case 'btt':
      return { x: buttonX, y: viewportHeight }
    case 'ltr':
    default:
      return { x: 0, y: buttonY }
  }
}

function waitForAnimationFrame() {
  return new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  })
}

function createThemeOverlay(targetTheme: 'light' | 'dark', clipFrom: string, x: number, y: number) {
  const overlay = document.createElement('div')
  const colors = overlayColors[targetTheme]

  overlay.className = 'magicui-theme-overlay'
  overlay.style.setProperty('--magicui-theme-overlay-bg', colors.background)
  overlay.style.setProperty('--magicui-theme-overlay-glow', colors.glow)
  overlay.style.setProperty('--magicui-theme-overlay-edge', colors.edge)
  overlay.style.setProperty('--magicui-theme-overlay-x', `${x}px`)
  overlay.style.setProperty('--magicui-theme-overlay-y', `${y}px`)
  overlay.style.clipPath = clipFrom
  overlay.style.webkitClipPath = clipFrom
  document.body.appendChild(overlay)

  return overlay
}

function animateOverlay(overlay: HTMLElement, clipPath: [string, string]) {
  const animation = overlay.animate(
    {
      clipPath,
      webkitClipPath: clipPath,
      transform: ['translateZ(0) scale(1)', 'translateZ(0) scale(1.003)'],
    },
    {
      duration: props.duration,
      easing: props.transitionVariant === 'star' ? 'linear' : 'cubic-bezier(0.65, 0, 0.35, 1)',
      fill: 'forwards',
    }
  )

  return animation
}

function removeOverlay(overlay: HTMLElement) {
  overlay.animate(
    {
      opacity: [1, 0],
      transform: ['translateZ(0) scale(1)', 'translateZ(0) scale(1.008)'],
    },
    {
      duration: 140,
      easing: 'ease-out',
      fill: 'forwards',
    }
  ).finished.finally(() => {
    overlay.remove()
  })
}

async function handleToggle() {
  if (props.disabled || isAnimating.value) return

  const nextTheme = getNextTheme()
  const button = getButtonElement()

  if (!button) {
    setTheme(nextTheme)
    return
  }

  const viewportWidth = window.visualViewport?.width ?? window.innerWidth
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight
  const { x, y } = getTransitionOrigin(button, viewportWidth, viewportHeight)
  const maxRadius = Math.hypot(
    Math.max(x, viewportWidth - x),
    Math.max(y, viewportHeight - y)
  )
  const clipPath = props.transitionVariant === 'rectangle'
    ? getDirectionalClipPaths(props.direction, viewportWidth, viewportHeight)
    : getShapeClipPaths(props.transitionVariant, x, y, maxRadius, viewportWidth, viewportHeight)

  isAnimating.value = true

  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    setTheme(nextTheme)
    isAnimating.value = false
    return
  }

  const targetTheme = getResolvedThemeForMode(nextTheme)
  const overlay = createThemeOverlay(targetTheme, clipPath[0], x, y)

  try {
    await waitForAnimationFrame()
    const animation = animateOverlay(overlay, clipPath)
    await animation.finished
    setTheme(nextTheme)
    await waitForAnimationFrame()
    removeOverlay(overlay)
  } catch {
    overlay.remove()
    setTheme(nextTheme)
  } finally {
    window.setTimeout(() => {
      isAnimating.value = false
    }, 80)
  }
}
</script>

<style>
.magicui-theme-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  pointer-events: none;
  overflow: hidden;
  background:
    radial-gradient(circle at var(--magicui-theme-overlay-x, 50%) var(--magicui-theme-overlay-y, 50%), var(--magicui-theme-overlay-edge), transparent 13vmax),
    radial-gradient(circle at var(--magicui-theme-overlay-x, 50%) var(--magicui-theme-overlay-y, 50%), var(--magicui-theme-overlay-glow), transparent 34vmax),
    var(--magicui-theme-overlay-bg);
  opacity: 1;
  transform: translateZ(0);
  will-change: clip-path, opacity, transform;
  contain: strict;
  backface-visibility: hidden;
}
</style>

<style scoped>
.animated-theme-toggler {
  contain: layout paint;
  transform: translateZ(0);
  will-change: transform;
}

.animated-theme-toggler__icon-stack {
  position: relative;
  display: inline-grid;
  width: 1.15em;
  height: 1.15em;
  place-items: center;
  flex: 0 0 auto;
}

.animated-theme-toggler__icon {
  grid-area: 1 / 1;
  opacity: 0;
  transform: rotate(-90deg) scale(0.35);
  filter: blur(4px);
  transition:
    opacity 0.22s ease,
    transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1),
    filter 0.22s ease,
    color 0.22s ease;
}

.animated-theme-toggler__icon.is-visible {
  opacity: 1;
  transform: rotate(0deg) scale(1);
  filter: blur(0);
}

.animated-theme-toggler__icon-sun {
  color: #f59e0b;
  filter: drop-shadow(0 0 5px rgba(245, 158, 11, 0.24));
}

.animated-theme-toggler__icon-moon {
  color: #2563eb;
  filter: drop-shadow(0 0 5px rgba(37, 99, 235, 0.22));
}

.animated-theme-toggler__icon-system {
  color: #64748b;
  filter: drop-shadow(0 0 5px rgba(100, 116, 139, 0.18));
}

.animated-theme-toggler__label {
  font-size: 12px;
  font-weight: 650;
  line-height: 1;
  letter-spacing: 0;
}

.animated-theme-toggler:hover .animated-theme-toggler__icon.is-visible {
  transform: rotate(-12deg) scale(1.1);
}

.animated-theme-toggler.is-animating {
  pointer-events: none;
}

.animated-theme-toggler.is-dark .animated-theme-toggler__icon-system {
  color: #cbd5e1;
}

@media (prefers-reduced-motion: reduce) {
  .animated-theme-toggler,
  .animated-theme-toggler__icon {
    transition-duration: 0.01ms !important;
  }
}
</style>
