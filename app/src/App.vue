<script setup lang="ts">
import { CircleAlert, LoaderCircle } from '@lucide/vue'
import { watch } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import BackendDrawer from './components/BackendDrawer.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import ToastStack from './components/ToastStack.vue'
import { setLanguage } from './i18n'
import BackendsPage from './pages/BackendsPage.vue'
import ClaudePage from './pages/ClaudePage.vue'
import HistoryPage from './pages/HistoryPage.vue'
import PlaygroundPage from './pages/PlaygroundPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import { loadAll, store } from './store'
import { setTheme } from './theme'

const pages = { backends: BackendsPage, playground: PlaygroundPage, history: HistoryPage, claude: ClaudePage, settings: SettingsPage }

watch(() => store.cfg?.ui.language, (lang) => lang && setLanguage(lang), { immediate: true })
watch(() => store.cfg?.ui.theme, (theme) => setTheme(theme ?? 'system'), { immediate: true })
</script>

<template>
  <div v-if="store.cfg" class="flex h-full">
    <AppSidebar />
    <main class="min-w-0 flex-1 overflow-y-auto">
      <div class="mx-auto max-w-6xl px-8 py-7">
        <KeepAlive :include="['PlaygroundPage']">
          <component :is="pages[store.page]" :key="store.page" />
        </KeepAlive>
      </div>
    </main>
    <BackendDrawer />
  </div>

  <div v-else class="grid h-full place-items-center p-6">
    <div v-if="store.loadError" class="card max-w-lg p-6">
      <div class="flex items-start gap-3">
        <CircleAlert class="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
        <div class="min-w-0">
          <h1 class="font-semibold">{{ $t('app.backendDown') }}</h1>
          <p class="mt-1 text-sm break-words whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">{{ store.loadError }}</p>
          <button class="btn-primary mt-4" @click="loadAll">{{ $t('app.retry') }}</button>
        </div>
      </div>
    </div>
    <div v-else class="flex items-center gap-3 text-sm text-zinc-500">
      <LoaderCircle class="h-5 w-5 animate-spin text-indigo-500" /> {{ $t('app.starting') }}
    </div>
  </div>

  <ToastStack />
  <ConfirmDialog />
</template>
