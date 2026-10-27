<script setup lang="ts">
import { Copy, FolderOpen, ImageOff, ImagePlus, RefreshCw, Search, Trash2 } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AGENT_LABELS, api, historyImageUrl, PROVIDER_NAMES, type HistoryEntry } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SideDrawer from '../components/SideDrawer.vue'
import { basename, dateTime, sourceLabel, timeAgo } from '../format'
import { copyText, revealPath } from '../platform'
import { confirmDialog, navigate, store, toast } from '../store'

const PAGE = 60
const { t } = useI18n()
const items = ref<HistoryEntry[]>([])
const total = ref(0)
const loading = ref(false)
const query = ref('')
const source = ref('')
const sources = ['playground', 'claude', 'codex', 'opencode', 'antigravity']
const backend = ref('')
const selected = ref<HistoryEntry | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined

const filters = computed(() => {
  const params = new URLSearchParams({ q: query.value })
  if (source.value) params.set('source', source.value)
  if (backend.value) params.set('backend', backend.value)
  return params
})

async function load(more = false) {
  loading.value = true
  try {
    const params = new URLSearchParams(filters.value)
    params.set('offset', String(more ? items.value.length : 0))
    params.set('limit', String(PAGE))
    const page = await api<{ items: HistoryEntry[]; total: number }>(`/api/history?${params}`)
    items.value = more ? [...items.value, ...page.items] : page.items
    total.value = page.total
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    loading.value = false
  }
}

watch([source, backend], () => load())
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(load, 250)
})
onMounted(load)

async function reveal(path: string) {
  if (!(await revealPath(path))) {
    await copyText(path)
    toast(t('common.pathCopied'))
  }
}
async function copy(path: string) {
  await copyText(path)
  toast(t('common.pathCopied'))
}
function editInPlayground(path: string) {
  store.playground.inputs = [path]
  selected.value = null
  navigate('playground')
}
async function remove(entry: HistoryEntry) {
  if (!(await confirmDialog(t('history.removeConfirm'), { confirmLabel: t('common.remove'), danger: true }))) return
  await api(`/api/history/${entry.id}`, { method: 'DELETE' })
  selected.value = null
  toast(t('history.removed'), 'success')
  load()
}
</script>

<template>
  <div>
    <PageHeader :title="$t('nav.history')" :subtitle="$t('history.subtitle')">
      <button class="btn-secondary" :disabled="loading" @click="load()">
        <RefreshCw :class="['h-4 w-4', loading && 'animate-spin']" /> {{ $t('common.refresh') }}
      </button>
    </PageHeader>

    <div class="mb-5 flex flex-wrap items-center gap-3">
      <div class="relative min-w-60 flex-1">
        <Search class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <input class="input pl-9" v-model="query" :placeholder="$t('history.searchPlaceholder')" />
      </div>
      <select class="input w-auto!" v-model="source">
        <option value="">{{ $t('history.allSources') }}</option>
        <option v-for="s in sources" :key="s" :value="s">{{ s === 'playground' ? $t('history.source.playground') : AGENT_LABELS[s] }}</option>
      </select>
      <select class="input w-auto!" v-model="backend">
        <option value="">{{ $t('history.allBackends') }}</option>
        <option v-for="n in PROVIDER_NAMES" :key="n" :value="n">{{ $t(`backends.names.${n}`) }}</option>
      </select>
      <span class="text-xs text-zinc-500 dark:text-zinc-400">{{ $t('history.count', { n: total }) }}</span>
    </div>

    <div v-if="!items.length && !loading" class="card grid place-items-center px-6 py-20 text-center">
      <ImageOff class="mb-3 h-8 w-8 text-zinc-300 dark:text-zinc-600" />
      <p class="font-medium">{{ $t('history.emptyTitle') }}</p>
      <p class="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">{{ $t('history.emptyText') }}</p>
    </div>

    <div class="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-4">
      <button
        v-for="entry in items"
        :key="entry.id"
        type="button"
        class="card group overflow-hidden text-left transition hover:-translate-y-0.5 hover:shadow-md"
        @click="selected = entry"
      >
        <div class="relative aspect-square bg-zinc-100 dark:bg-zinc-950">
          <img
            v-if="entry.outputs?.length && !entry.missing?.[0]"
            :src="historyImageUrl(entry.id, 'outputs', 0, true)"
            loading="lazy"
            class="h-full w-full object-cover"
            :alt="entry.prompt"
          />
          <div v-else class="grid h-full place-items-center text-xs text-zinc-400"><ImageOff class="h-6 w-6" /></div>
          <span class="badge absolute top-2 left-2 bg-white/90 text-zinc-700 shadow-sm dark:bg-zinc-900/90 dark:text-zinc-300">
            {{ sourceLabel(entry.source) }}
          </span>
          <span v-if="(entry.outputs?.length ?? 0) > 1" class="badge absolute top-2 right-2 bg-zinc-900/75 text-white">×{{ entry.outputs!.length }}</span>
        </div>
        <div class="p-3">
          <p class="line-clamp-2 text-[13px] leading-snug">{{ entry.prompt }}</p>
          <p class="mt-1.5 truncate text-[11px] text-zinc-500 dark:text-zinc-400">
            {{ entry.backend ? $t(`backends.names.${entry.backend}`) : '' }} · {{ timeAgo(entry.time) }}
          </p>
        </div>
      </button>
    </div>

    <div v-if="items.length < total" class="mt-6 text-center">
      <button class="btn-secondary" :disabled="loading" @click="load(true)">{{ $t('history.loadMore') }}</button>
    </div>

    <SideDrawer :open="!!selected" wide :title="$t('history.details')" :subtitle="selected ? dateTime(selected.time) : ''" @close="selected = null">
      <template v-if="selected">
        <div class="space-y-4">
          <div v-for="(path, i) in selected.outputs" :key="path" class="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
            <img
              v-if="!selected.missing?.[i]"
              :src="historyImageUrl(selected.id, 'outputs', i)"
              class="max-h-[55vh] w-full bg-zinc-100 object-contain dark:bg-zinc-950"
              :alt="selected.prompt"
            />
            <div v-else class="grid h-40 place-items-center bg-zinc-100 text-sm text-zinc-500 dark:bg-zinc-950">{{ $t('history.missing') }}</div>
            <div class="flex flex-wrap items-center gap-1.5 border-t border-zinc-200 px-3 py-2 dark:border-zinc-800">
              <span class="mono min-w-0 flex-1 truncate text-zinc-500 dark:text-zinc-400" :title="path">{{ path }}</span>
              <button class="btn-ghost btn-sm" @click="reveal(path)"><FolderOpen class="h-3.5 w-3.5" /> {{ $t('common.showInFolder') }}</button>
              <button class="btn-ghost btn-sm" @click="copy(path)"><Copy class="h-3.5 w-3.5" /> {{ $t('common.copyPath') }}</button>
              <button class="btn-secondary btn-sm" :disabled="selected.missing?.[i]" @click="editInPlayground(path)">
                <ImagePlus class="h-3.5 w-3.5" /> {{ $t('history.editInPlayground') }}
              </button>
            </div>
          </div>

          <dl class="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-sm">
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.prompt') }}</dt>
            <dd class="leading-relaxed whitespace-pre-wrap">{{ selected.prompt }}</dd>
            <template v-if="selected.negative_prompt">
              <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.negative') }}</dt>
              <dd>{{ selected.negative_prompt }}</dd>
            </template>
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.backend') }}</dt>
            <dd>{{ selected.backend ? $t(`backends.names.${selected.backend}`) : '—' }} <span class="mono text-zinc-500">({{ selected.model }})</span></dd>
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.size') }}</dt>
            <dd>{{ selected.width }}×{{ selected.height }}<template v-if="(selected.n ?? 1) > 1"> · ×{{ selected.n }}</template></dd>
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.seed') }}</dt>
            <dd>{{ selected.seed ?? $t('history.random') }}</dd>
            <template v-if="selected.strength != null">
              <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.strength') }}</dt>
              <dd>{{ selected.strength }}</dd>
            </template>
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.sourceLabel') }}</dt>
            <dd>{{ sourceLabel(selected.source) }}<span v-if="selected.client" class="mono text-zinc-500"> ({{ selected.client }})</span></dd>
            <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.folder') }}</dt>
            <dd class="mono break-all">{{ selected.cwd }}</dd>
            <template v-if="selected.inputs?.length">
              <dt class="text-zinc-500 dark:text-zinc-400">{{ $t('history.inputs') }}</dt>
              <dd class="flex flex-wrap gap-2">
                <img
                  v-for="(path, i) in selected.inputs"
                  :key="path"
                  :src="historyImageUrl(selected.id, 'inputs', i, true)"
                  :title="basename(path)"
                  class="h-16 w-16 rounded-md border border-zinc-200 object-cover dark:border-zinc-700"
                  alt=""
                />
              </dd>
            </template>
          </dl>
        </div>
      </template>
      <template #footer>
        <div v-if="selected" class="flex justify-end">
          <button class="btn-danger" @click="remove(selected)"><Trash2 class="h-4 w-4" /> {{ $t('history.remove') }}</button>
        </div>
      </template>
    </SideDrawer>
  </div>
</template>
