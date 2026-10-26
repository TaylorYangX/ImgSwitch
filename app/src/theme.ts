// Applies Settings → Theme: an explicit light/dark choice, or whatever the OS prefers.
const media = window.matchMedia('(prefers-color-scheme: dark)')
let current: 'system' | 'light' | 'dark' = 'system'

function apply(): void {
  const dark = current === 'dark' || (current === 'system' && media.matches)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

media.addEventListener('change', apply)

export function setTheme(theme: 'system' | 'light' | 'dark'): void {
  current = theme
  apply()
}
