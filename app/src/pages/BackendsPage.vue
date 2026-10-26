<script setup lang="ts">
import { Cloud, Cpu, ImagePlus, Pencil, PlugZap, RefreshCw } from '@lucide/vue'
import { reactive } from 'vue'
import { api, PROVIDER_NAMES, type HealthStatus, type ProviderName } from '../api'
import PageHeader from '../components/PageHeader.vue'
import StatusDot from '../components/StatusDot.vue'
import ToggleSwitch from '../components/ToggleSwitch.vue'
import { backendInfo, refreshBackends, setActive, store } from '../store'

const testing = reactive<Record<string, boolean>>({})
const results = reactive<Record<string, HealthStatus>>({})

async function test(name: ProviderName) {
  testing[name] = true
  try {
    results[name] = await api<HealthStatus>(`/api/providers/${name}/test`, { method: 'POST', json: store.cfg!.providers[name] })
  } catch (e) {
    results[name] = { ok: false, detail: (e as Error).message, latency_ms: null }
  } finally {
    testing[name] = false
  }
}

function status(name: ProviderName): HealthStatus | undefined {
  return results[name] ?? backendInfo(name)
}
</script>

<template>
  <div v-if="store.cfg">
    <PageHeader :title="$t('nav.backends')" :subtitle="$t('backends.subtitle')">
      <button class="btn-secondary" :disabled="store.backendsLoading" @click="refreshBackends">
        <RefreshCw :class="['h-4 w-4', store.backendsLoading && 'animate-spin']" /> {{ $t('common.refresh') }}
      </button>
    </PageHeader>

    <div class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="name in PROVIDER_NAMES"
        :key="name"
        :class="[
          'card flex flex-col transition',
          store.cfg.active_provider === name ? 'ring-2 ring-indigo-500/80 dark:ring-indigo-400/70' : '',
          store.cfg.providers[name].enabled ? '' : 'opacity-70',
        ]"
      >
        <div class="flex items-start gap-4 p-5">
          <div
            :class="[
              'grid h-10 w-10 shrink-0 place-items-center rounded-xl',
              name === 'openai'
                ? 'bg-sky-50 text-sky-600 dark:bg-sky-500/15 dark:text-sky-300'
                : 'bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300',
            ]"
          >
            <Cloud v-if="name === 'openai'" class="h-5 w-5" />
            <Cpu v-else class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h2 class="truncate text-[15px] font-semibold">{{ $t(`backends.names.${name}`) }}</h2>
              <span class="badge bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                {{ name === 'openai' ? $t('backends.cloud') : $t('backends.local') }}
              </span>
              <span v-if="store.cfg.active_provider === name" class="badge bg-indigo-600 text-white">{{ $t('common.active') }}</span>
            </div>
            <p class="mono mt-1 truncate text-zinc-500 dark:text-zinc-400">{{ store.cfg.providers[name].base_url }}</p>
            <div class="mt-3 space-y-1.5 text-[13px]">
              <p class="flex items-center gap-2">
                <StatusDot :ok="status(name)?.ok" />
                <span
                  :class="['truncate', status(name) && !status(name)!.ok ? 'text-red-600 dark:text-red-400' : 'text-zinc-700 dark:text-zinc-300']"
                  :title="status(name)?.detail"
                >
                  {{ status(name)?.detail ?? $t('common.checking') }}
                  <span v-if="status(name)?.latency_ms != null" class="text-zinc-400">· {{ status(name)!.latency_ms }} ms</span>
                </span>
              </p>
              <p v-if="backendInfo(name)" class="flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
                <ImagePlus class="h-3.5 w-3.5 shrink-0" />
                <span class="truncate" :title="backendInfo(name)!.image_input">{{ $t('backends.imageInput') }}: {{ backendInfo(name)!.image_input }}</span>
              </p>
            </div>
          </div>
        </div>

        <footer class="mt-auto flex flex-wrap items-center gap-2 border-t border-zinc-100 px-5 py-3 dark:border-zinc-800">
          <label
            class="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400"
            :title="store.cfg.active_provider === name ? $t('backends.activeLocked') : $t('backends.availableHint')"
          >
            <ToggleSwitch v-model="store.cfg.providers[name].enabled" :disabled="store.cfg.active_provider === name" />
            {{ store.cfg.providers[name].enabled ? $t('backends.available') : $t('backends.notAvailable') }}
          </label>
          <div class="ml-auto flex items-center gap-2">
            <button class="btn-ghost btn-sm" :disabled="testing[name]" @click="test(name)">
              <PlugZap class="h-3.5 w-3.5" /> {{ testing[name] ? $t('common.testing') : $t('common.test') }}
            </button>
            <button class="btn-secondary btn-sm" @click="store.editing = name"><Pencil class="h-3.5 w-3.5" /> {{ $t('common.edit') }}</button>
            <button v-if="store.cfg.active_provider !== name" class="btn-primary btn-sm" @click="setActive(name)">
              {{ $t('backends.setActive') }}
            </button>
          </div>
        </footer>
      </article>
    </div>

    <p class="hint mt-6">{{ $t('backends.footnote') }}</p>
  </div>
</template>
