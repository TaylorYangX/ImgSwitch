<script setup lang="ts">
import { Bot, Check, ChevronsUpDown, CircleAlert, History, Images, LoaderCircle, Server, Settings, WandSparkles } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ProviderName } from '../api'
import { PROVIDER_NAMES } from '../api'
import { backendInfo, navigate, setActive, store, type Page } from '../store'
import StatusDot from './StatusDot.vue'

const nav: { page: Page; icon: unknown }[] = [
  { page: 'backends', icon: Server },
  { page: 'playground', icon: WandSparkles },
  { page: 'history', icon: History },
  { page: 'agents', icon: Bot },
  { page: 'settings', icon: Settings },
]

const open = ref(false)
const switcher = ref<HTMLElement>()
const active = computed(() => store.cfg?.active_provider)
const choices = computed(() => PROVIDER_NAMES.filter((n) => store.cfg?.providers[n].enabled))

function choose(name: ProviderName) {
  setActive(name)
  open.value = false
}

function closeOnOutside(e: MouseEvent) {
  if (open.value && !switcher.value?.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', closeOnOutside))
onBeforeUnmount(() => document.removeEventListener('click', closeOnOutside))
</script>

<template>
  <aside class="flex w-60 shrink-0 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
    <div class="flex items-center gap-3 px-5 pt-5 pb-6">
      <div class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 text-white shadow-sm">
        <Images class="h-5 w-5" />
      </div>
      <div class="min-w-0">
        <p class="text-[15px] leading-tight font-semibold">ImgSwitch</p>
        <p class="text-[11px] leading-snug text-zinc-500 dark:text-zinc-400">{{ $t('app.tagline') }}</p>
      </div>
    </div>

    <nav class="flex-1 space-y-0.5 px-3">
      <button
        v-for="item in nav"
        :key="item.page"
        type="button"
        @click="navigate(item.page)"
        :class="[
          'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition',
          store.page === item.page
            ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300'
            : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100',
        ]"
      >
        <component :is="item.icon" class="h-4 w-4" />
        {{ $t(`nav.${item.page}`) }}
      </button>
    </nav>

    <div class="space-y-3 p-3">
      <div ref="switcher" class="relative">
        <p class="mb-1.5 px-1 text-[11px] font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
          {{ $t('switcher.label') }}
        </p>
        <button
          type="button"
          class="flex w-full items-center gap-2.5 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-sm transition hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:border-zinc-600"
          @click="open = !open"
        >
          <StatusDot :ok="active ? backendInfo(active)?.ok : null" />
          <span class="min-w-0 flex-1 truncate font-medium">{{ active ? $t(`backends.names.${active}`) : '—' }}</span>
          <ChevronsUpDown class="h-4 w-4 text-zinc-400" />
        </button>
        <Transition enter-from-class="opacity-0 translate-y-1" leave-to-class="opacity-0" enter-active-class="transition" leave-active-class="transition">
          <div v-if="open" class="card absolute right-0 bottom-full left-0 z-30 mb-1.5 overflow-hidden p-1 shadow-lg">
            <button
              v-for="name in choices"
              :key="name"
              type="button"
              class="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
              @click="choose(name)"
            >
              <StatusDot :ok="backendInfo(name)?.ok" />
              <span class="min-w-0 flex-1">
                <span class="block truncate">{{ $t(`backends.names.${name}`) }}</span>
                <span class="block truncate text-[11px] text-zinc-500 dark:text-zinc-400">{{ backendInfo(name)?.detail }}</span>
              </span>
              <Check v-if="name === active" class="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
            </button>
          </div>
        </Transition>
      </div>

      <div class="flex items-center gap-1.5 px-1 text-[11px] text-zinc-500 dark:text-zinc-400" :title="store.saveError">
        <LoaderCircle v-if="store.saveState === 'saving' || store.saveState === 'pending'" class="h-3 w-3 animate-spin" />
        <CircleAlert v-else-if="store.saveState === 'error'" class="h-3 w-3 text-red-500" />
        <Check v-else class="h-3 w-3 text-emerald-500" />
        <span :class="['truncate', store.saveState === 'error' && 'text-red-600 dark:text-red-400']">
          {{ store.saveState === 'error' ? $t('save.error', { error: store.saveError }) : $t(`save.${store.saveState === 'pending' ? 'saving' : store.saveState === 'idle' ? 'saved' : store.saveState}`) }}
        </span>
        <span class="ml-auto shrink-0">v{{ store.meta?.version }}</span>
      </div>
    </div>
  </aside>
</template>
