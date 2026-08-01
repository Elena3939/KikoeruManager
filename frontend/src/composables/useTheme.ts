import { computed, readonly, ref, type ComputedRef, type Ref } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export interface UseThemeOptions {
  storageKey?: string
  defaultTheme?: ThemeMode
  darkClass?: string
  legacyDarkClass?: string
}

export interface UseThemeReturn {
  theme: Readonly<Ref<ThemeMode>>
  resolvedTheme: Readonly<Ref<ResolvedTheme>>
  isDark: Readonly<ComputedRef<boolean>>
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => ThemeMode
  applyTheme: () => void
}

const THEME_STORAGE_KEY = 'kikoerumanager.theme'
const DEFAULT_THEME: ThemeMode = 'system'
const DARK_CLASS = 'dark'
const LEGACY_DARK_CLASS = 'kikoerumanager-dark'
const THEME_ORDER: ThemeMode[] = ['light', 'dark', 'system']

const themeState = ref<ThemeMode>(DEFAULT_THEME)
const resolvedThemeState = ref<ResolvedTheme>('light')
let mediaQuery: MediaQueryList | null = null
let mediaQueryBound = false

function isThemeMode(value: string | null): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

function getBrowserPreferredTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(theme: ThemeMode): ResolvedTheme {
  return theme === 'system' ? getBrowserPreferredTheme() : theme
}

function getStoredTheme(storageKey = THEME_STORAGE_KEY, defaultTheme = DEFAULT_THEME): ThemeMode {
  if (typeof window === 'undefined') return defaultTheme
  const storedTheme = window.localStorage.getItem(storageKey)
  return isThemeMode(storedTheme) ? storedTheme : defaultTheme
}

function persistTheme(theme: ThemeMode, storageKey = THEME_STORAGE_KEY) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(storageKey, theme)
}

function updateThemeColor(resolvedTheme: ResolvedTheme) {
  if (typeof document === 'undefined') return
  const themeColorMeta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (themeColorMeta) {
    themeColorMeta.setAttribute('content', resolvedTheme === 'dark' ? '#08090d' : '#ffffff')
  }
}

function applyResolvedTheme(
  resolvedTheme: ResolvedTheme,
  darkClass = DARK_CLASS,
  legacyDarkClass = LEGACY_DARK_CLASS
) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const body = document.body
  const isDark = resolvedTheme === 'dark'

  root.classList.toggle(darkClass, isDark)
  root.classList.toggle(legacyDarkClass, isDark)
  root.style.colorScheme = resolvedTheme
  body?.classList.toggle(legacyDarkClass, isDark)
  updateThemeColor(resolvedTheme)
}

function commitTheme(
  theme: ThemeMode,
  options: Required<UseThemeOptions>,
  shouldPersist = true
) {
  const resolvedTheme = resolveTheme(theme)
  themeState.value = theme
  resolvedThemeState.value = resolvedTheme
  applyResolvedTheme(resolvedTheme, options.darkClass, options.legacyDarkClass)
  if (shouldPersist) persistTheme(theme, options.storageKey)
}

function bindSystemThemeListener(options: Required<UseThemeOptions>) {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function' || mediaQueryBound) {
    return
  }

  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  const handleSystemThemeChange = () => {
    if (themeState.value !== 'system') return
    commitTheme('system', options, false)
  }

  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', handleSystemThemeChange)
  } else {
    mediaQuery.addListener(handleSystemThemeChange)
  }
  mediaQueryBound = true
}

function normalizeOptions(options: UseThemeOptions = {}): Required<UseThemeOptions> {
  return {
    storageKey: options.storageKey ?? THEME_STORAGE_KEY,
    defaultTheme: options.defaultTheme ?? DEFAULT_THEME,
    darkClass: options.darkClass ?? DARK_CLASS,
    legacyDarkClass: options.legacyDarkClass ?? LEGACY_DARK_CLASS,
  }
}

export function initializeTheme(options: UseThemeOptions = {}) {
  if (typeof window === 'undefined') return
  const normalizedOptions = normalizeOptions(options)
  const initialTheme = getStoredTheme(normalizedOptions.storageKey, normalizedOptions.defaultTheme)
  commitTheme(initialTheme, normalizedOptions, false)
  bindSystemThemeListener(normalizedOptions)
}

export function useTheme(options: UseThemeOptions = {}): UseThemeReturn {
  const normalizedOptions = normalizeOptions(options)

  initializeTheme(normalizedOptions)

  const isDark = computed(() => resolvedThemeState.value === 'dark')

  function setTheme(theme: ThemeMode) {
    commitTheme(theme, normalizedOptions, true)
  }

  function toggleTheme() {
    const currentIndex = THEME_ORDER.indexOf(themeState.value)
    const nextTheme = THEME_ORDER[(currentIndex + 1) % THEME_ORDER.length]
    setTheme(nextTheme)
    return nextTheme
  }

  function applyTheme() {
    commitTheme(themeState.value, normalizedOptions, false)
  }

  return {
    theme: readonly(themeState),
    resolvedTheme: readonly(resolvedThemeState),
    isDark: readonly(isDark),
    setTheme,
    toggleTheme,
    applyTheme,
  }
}

initializeTheme()
