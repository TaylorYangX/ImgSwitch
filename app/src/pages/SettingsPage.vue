<script setup lang="ts">
import { Copy, FolderOpen, Monitor, Moon, Sun, Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import { api, apiUrl, isTauri } from '../api'
import PageHeader from '../components/PageHeader.vue'
import ToggleSwitch from '../components/ToggleSwitch.vue'
import { copyText, revealPath } from '../platform'
import { confirmDialog, store, toast } from '../store'

const { t } = useI18n()
const backendUrl = apiUrl('') || window.location.origin
const themes = [
  { value: 'system', icon: Monitor },
  { value: 'light', icon: Sun },
  { value: 'dark', icon: Moon },
] as const

async function reveal(path: string) {
  if (!(await revealPath(path))) {
    await copyText(path)
    toast(t('common.pathCopied'))
  }
}
async function copy(text: string) {
  await copyText(text)
  toast(t('common.copied'))
}
async function clearHistory() {
  if (!(await confirmDialog(t('settings.data.clearConfirm'), { confirmLabel: t('settings.data.clear'), danger: true }))) return
  const { removed } = await api<{ removed: number }>('/api/history', { method: 'DELETE' })
  toast(t('settings.data.cleared', { n: removed }), 'success')
}
</script>

<template>
  <div v-if="store.cfg && store.meta" class="max-w-3xl">
    <PageHeader :title="$t('nav.settings')" :subtitle="$t('settings.subtitle')" />

    <div class="space-y-5">
      <section class="card p-5">
        <h2 class="mb-4 font-semibold">{{ $t('settings.appearance') }}</h2>
        <div class="grid gap-5 sm:grid-cols-2">
          <div>
            <label class="field-label">{{ $t('settings.language') }}</label>
            <select class="input" v-model="store.cfg.ui.language">
              <option value="en">English</option>
              <option value="zh-CN">简体中文</option>
            </select>
          </div>
          <div>
            <label class="field-label">{{ $t('settings.theme') }}</label>
            <div class="flex rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
              <button
                v-for="th in themes"
                :key="th.value"
                type="button"
                :class="['flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-sm transition', store.cfg.ui.theme === th.value ? 'bg-indigo-600 text-white' : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800']"
                @click="store.cfg.ui.theme = th.value"
              >
                <component :is="th.icon" class="h-3.5 w-3.5" /> {{ $t(`settings.themes.${th.value}`) }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section class="card space-y-5 p-5">
        <h2 class="font-semibold">{{ $t('settings.output.title') }}</h2>
        <div>
          <label class="field-label">{{ $t('settings.output.folder') }}</label>
          <input class="input mono" v-model.trim="store.cfg.output.dir" placeholder="." spellcheck="false" />
          <p class="hint">{{ $t('settings.output.folderHint') }}</p>
        </div>
        <div class="flex items-start justify-between gap-6">
          <div>
            <p class="field-label mb-0.5">{{ $t('settings.output.inline') }}</p>
            <p class="hint mt-0">{{ $t('settings.output.inlineHint') }}</p>
          </div>
          <ToggleSwitch v-model="store.cfg.output.return_inline" />
        </div>
        <div class="max-w-56">
          <label class="field-label">{{ $t('settings.output.inlineMax') }}</label>
          <input class="input" type="number" min="128" max="4096" step="64" v-model.number="store.cfg.output.inline_max_px" :disabled="!store.cfg.output.return_inline" />
        </div>
        <div>
          <label class="field-label">{{ $t('settings.output.playground') }}</label>
          <input class="input mono" v-model.trim="store.cfg.output.playground_dir" spellcheck="false" />
          <p class="hint">{{ $t('settings.output.playgroundHint') }}</p>
        </div>
      </section>

      <section class="card p-5">
        <h2 class="mb-4 font-semibold">{{ $t('settings.data.title') }}</h2>
        <div class="space-y-3">
          <div v-for="row in [{ label: $t('settings.data.config'), path: store.meta.config_path }, { label: $t('settings.data.history'), path: store.meta.history_path }]" :key="row.label" class="flex items-center gap-3">
            <span class="w-28 shrink-0 text-sm text-zinc-500 dark:text-zinc-400">{{ row.label }}</span>
            <span class="mono min-w-0 flex-1 truncate" :title="row.path">{{ row.path }}</span>
            <button class="btn-ghost btn-sm" @click="copy(row.path)"><Copy class="h-3.5 w-3.5" /></button>
            <button v-if="isTauri" class="btn-ghost btn-sm" @click="reveal(row.path)"><FolderOpen class="h-3.5 w-3.5" /></button>
          </div>
        </div>
        <div class="mt-5 flex items-center justify-between gap-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p class="text-sm text-zinc-600 dark:text-zinc-400">{{ $t('settings.data.clearHint') }}</p>
          <button class="btn-danger shrink-0" @click="clearHistory"><Trash2 class="h-4 w-4" /> {{ $t('settings.data.clear') }}</button>
        </div>
      </section>

      <section class="card p-5">
        <h2 class="mb-4 font-semibold">{{ $t('settings.about.title') }}</h2>
        <dl class="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('settings.about.version') }}</dt>
          <dd>ImgSwitch {{ store.meta.version }}</dd>
          <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('settings.about.mode') }}</dt>
          <dd>{{ isTauri ? $t('settings.about.modeApp') : $t('settings.about.modeBrowser') }}</dd>
          <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('settings.about.project') }}</dt>
          <dd class="mono truncate" :title="store.meta.project_root">{{ store.meta.project_root }}</dd>
          <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('settings.about.backend') }}</dt>
          <dd class="mono truncate">{{ backendUrl }}</dd>
          <dt class="text-zinc-500 dark:text-zinc-400">Python</dt>
          <dd class="mono truncate" :title="store.meta.python">{{ store.meta.python }}</dd>
        </dl>
      </section>
    </div>
  </div>
</template>
