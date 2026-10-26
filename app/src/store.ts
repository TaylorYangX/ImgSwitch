// App-wide state: the config (auto-saved), backend status, navigation, toasts and confirmations.
import { nextTick, reactive, watch } from 'vue'
import { api, type BackendInfo, type Config, type Meta, type ProviderName } from './api'

export type Page = 'backends' | 'playground' | 'history' | 'claude' | 'settings'
export const PAGES: Page[] = ['backends', 'playground', 'history', 'claude', 'settings']

export interface Toast {
  id: number
  message: string
  kind: 'info' | 'success' | 'error'
}

interface ConfirmRequest {
  message: string
  confirmLabel?: string
  danger?: boolean
  resolve: (ok: boolean) => void
}

export const store = reactive({
  cfg: null as Config | null,
  meta: null as Meta | null,
  loadError: '',
  backends: [] as BackendInfo[],
  backendsLoading: false,
  saveState: 'idle' as 'idle' | 'pending' | 'saving' | 'saved' | 'error',
  saveError: '',
  page: 'backends' as Page,
  editing: null as ProviderName | null,
  // Kept here so a half-written prompt survives switching pages, and History can hand images over.
  playground: { prompt: '', inputs: [] as string[] },
  toasts: [] as Toast[],
  confirm: null as ConfirmRequest | null,
})

let toastId = 0
export function toast(message: string, kind: Toast['kind'] = 'info'): void {
  const id = ++toastId
  store.toasts.push({ id, message, kind })
  setTimeout(() => (store.toasts = store.toasts.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 3500)
}

export function confirmDialog(message: string, options: { confirmLabel?: string; danger?: boolean } = {}): Promise<boolean> {
  return new Promise((resolve) => (store.confirm = { message, ...options, resolve }))
}

export function navigate(page: Page): void {
  store.page = page
  if (location.hash !== `#/${page}`) history.replaceState(null, '', `#/${page}`)
}

function pageFromHash(): void {
  const page = location.hash.replace(/^#\/?/, '') as Page
  if (PAGES.includes(page)) store.page = page
}

// ---- Config: load once, then save every change after a short pause ------------------------------

let loaded = false
let saveTimer: ReturnType<typeof setTimeout> | undefined

export async function loadAll(): Promise<void> {
  store.loadError = ''
  try {
    const [cfg, meta] = await Promise.all([api<Config>('/api/config'), api<Meta>('/api/meta')])
    loaded = false
    store.cfg = cfg
    store.meta = meta
    await nextTick()
    loaded = true
  } catch (e) {
    store.loadError = (e as Error).message
    return
  }
  refreshBackends()
}

async function save(): Promise<void> {
  store.saveState = 'saving'
  try {
    await api('/api/config', { method: 'PUT', json: store.cfg })
    store.saveState = 'saved'
    store.saveError = ''
    setTimeout(refreshBackends, 300)
  } catch (e) {
    store.saveState = 'error'
    store.saveError = (e as Error).message
  }
}

watch(
  () => store.cfg,
  () => {
    if (!loaded) return
    store.saveState = 'pending'
    clearTimeout(saveTimer)
    saveTimer = setTimeout(save, 500)
  },
  { deep: true },
)

// ---- Backend status --------------------------------------------------------------------------

let refreshing: Promise<void> | null = null
export function refreshBackends(): Promise<void> {
  if (document.visibilityState === 'hidden') return Promise.resolve() // don't ping cloud APIs from a hidden window
  refreshing ??= (async () => {
    store.backendsLoading = true
    try {
      store.backends = await api<BackendInfo[]>('/api/backends')
    } catch {
      /* backend gone; keep the last state */
    } finally {
      store.backendsLoading = false
      refreshing = null
    }
  })()
  return refreshing
}

export function backendInfo(name: ProviderName): BackendInfo | undefined {
  return store.backends.find((b) => b.name === name)
}

/** Make a backend the active one; it must be available to Claude, so that's switched on too. */
export function setActive(name: ProviderName): void {
  if (!store.cfg) return
  store.cfg.providers[name].enabled = true
  store.cfg.active_provider = name
}

export function startApp(): void {
  pageFromHash()
  window.addEventListener('hashchange', pageFromHash)
  setInterval(refreshBackends, 30000)
  document.addEventListener('visibilitychange', () => refreshBackends())
}
