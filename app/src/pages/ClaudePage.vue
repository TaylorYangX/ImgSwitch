<script setup lang="ts">
import { CircleAlert, CircleCheck, Copy, RefreshCw, ShieldCheck, SquareTerminal, TriangleAlert } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, type ClaudeStatus } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { dateTime, shortPath, timeAgo } from '../format'
import { copyText } from '../platform'
import { store, toast } from '../store'

const { t } = useI18n()
const status = ref<ClaudeStatus | null>(null)
const loading = ref(false)
const busy = ref(false)

const user = computed(() => status.value?.registrations.find((r) => r.scope === 'user'))
const registrationState = computed(() => {
  if (!status.value) return null
  if (!status.value.registrations.length) return 'missing'
  if (user.value && user.value.points_here && user.value.command_exists) return 'ok'
  if (status.value.registrations.some((r) => !r.command_exists)) return 'broken'
  return 'elsewhere'
})
const command = computed(() => store.meta?.claude_command ?? '')
const allAllowed = computed(() => !!status.value && Object.values(status.value.permissions.allowed).every(Boolean))
const outdated = computed(() => status.value?.servers.filter((s) => s.outdated).length ?? 0)

async function load() {
  loading.value = true
  try {
    status.value = await api<ClaudeStatus>('/api/claude')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    loading.value = false
  }
}
async function register() {
  busy.value = true
  try {
    const r = await api<{ ok: boolean; output: string }>('/api/claude/register', { method: 'POST' })
    toast(r.ok ? t('claude.registration.done') : r.output, r.ok ? 'success' : 'error')
    await load()
  } finally {
    busy.value = false
  }
}
async function allow() {
  busy.value = true
  try {
    await api('/api/claude/permissions', { method: 'POST' })
    toast(t('claude.permissions.done'), 'success')
    await load()
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    busy.value = false
  }
}
async function copy(text: string) {
  await copyText(text)
  toast(t('common.copied'))
}
onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="$t('nav.claude')" :subtitle="$t('claude.subtitle')">
      <button class="btn-secondary" :disabled="loading" @click="load">
        <RefreshCw :class="['h-4 w-4', loading && 'animate-spin']" /> {{ $t('common.refresh') }}
      </button>
    </PageHeader>

    <div v-if="status" class="space-y-5">
      <!-- Registration -->
      <section class="card p-5">
        <div class="flex items-start gap-3">
          <CircleCheck v-if="registrationState === 'ok'" class="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
          <TriangleAlert v-else-if="registrationState === 'elsewhere'" class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
          <CircleAlert v-else class="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
          <div class="min-w-0 flex-1">
            <h2 class="font-semibold">{{ $t('claude.registration.title') }}</h2>
            <p class="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">{{ $t(`claude.registration.${registrationState}`) }}</p>
            <ul v-if="status.registrations.length" class="mt-3 space-y-2">
              <li v-for="r in status.registrations" :key="`${r.scope}${r.project}`" class="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-950">
                <p class="flex flex-wrap items-center gap-2 text-xs">
                  <span class="badge bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">{{ $t(`claude.registration.scope.${r.scope}`) }}</span>
                  <span v-if="r.project" class="mono text-zinc-500">{{ r.project }}</span>
                  <span v-if="!r.command_exists" class="badge bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300">{{ $t('claude.registration.commandMissing') }}</span>
                  <span v-else-if="!r.points_here" class="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">{{ $t('claude.registration.otherCopy') }}</span>
                </p>
                <p class="mono mt-1.5 break-all text-zinc-600 dark:text-zinc-400">{{ r.url ?? [r.command, ...r.args].join(' ') }}</p>
              </li>
            </ul>
            <div v-if="registrationState !== 'ok'" class="mt-4 space-y-2">
              <div class="flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 dark:bg-black">
                <SquareTerminal class="h-4 w-4 shrink-0 text-zinc-400" />
                <code class="mono min-w-0 flex-1 truncate text-zinc-100" :title="command">{{ command }}</code>
                <button class="btn-ghost btn-sm text-zinc-300 hover:bg-zinc-800" @click="copy(command)"><Copy class="h-3.5 w-3.5" /></button>
              </div>
              <button v-if="!user" class="btn-primary" :disabled="busy || !status.cli" @click="register">{{ $t('claude.registration.register') }}</button>
              <p v-if="!status.cli" class="hint">{{ $t('claude.registration.cliMissing') }}</p>
              <p v-else class="hint">{{ $t('claude.registration.registerHint') }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- Permissions -->
      <section class="card p-5">
        <div class="flex items-start gap-3">
          <ShieldCheck :class="['mt-0.5 h-5 w-5 shrink-0', allAllowed ? 'text-emerald-500' : 'text-zinc-400']" />
          <div class="min-w-0 flex-1">
            <h2 class="font-semibold">{{ $t('claude.permissions.title') }}</h2>
            <p class="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">{{ $t('claude.permissions.desc') }}</p>
            <ul class="mt-3 space-y-1.5">
              <li v-for="(ok, tool) in status.permissions.allowed" :key="tool" class="flex items-center gap-2 text-sm">
                <code class="mono">{{ tool }}</code>
                <span :class="['badge', ok ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400']">
                  {{ ok ? $t('claude.permissions.allowed') : $t('claude.permissions.asks') }}
                </span>
              </li>
            </ul>
            <div class="mt-4 flex flex-wrap items-center gap-3">
              <button v-if="!allAllowed" class="btn-primary" :disabled="busy" @click="allow">{{ $t('claude.permissions.allow') }}</button>
              <span class="hint mt-0!">{{ $t('claude.permissions.file') }} <span class="mono">{{ status.permissions.settings_path }}</span></span>
            </div>
          </div>
        </div>
      </section>

      <!-- Running servers -->
      <section class="card overflow-hidden">
        <div class="flex items-start gap-3 p-5 pb-3">
          <TriangleAlert v-if="outdated" class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
          <CircleCheck v-else class="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
          <div>
            <h2 class="font-semibold">{{ $t('claude.servers.title') }}</h2>
            <p class="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
              {{ outdated ? $t('claude.servers.outdatedHint', { n: outdated }) : $t('claude.servers.desc') }}
            </p>
          </div>
        </div>
        <table v-if="status.servers.length" class="w-full table-fixed text-sm">
          <thead class="border-y border-zinc-100 bg-zinc-50 text-left text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
            <tr>
              <th class="px-5 py-2 font-medium">{{ $t('claude.servers.folder') }}</th>
              <th class="w-36 px-3 py-2 font-medium">{{ $t('claude.servers.started') }}</th>
              <th class="w-24 px-3 py-2 font-medium">PID</th>
              <th class="w-48 px-5 py-2 font-medium">{{ $t('claude.servers.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in status.servers" :key="s.pid" class="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
              <td class="mono truncate px-5 py-2.5" :title="s.cwd">{{ shortPath(s.cwd) }}</td>
              <td class="px-3 py-2.5 whitespace-nowrap text-zinc-600 dark:text-zinc-400" :title="dateTime(s.started_at)">{{ timeAgo(s.started_at) }}</td>
              <td class="mono px-3 py-2.5 text-zinc-500">{{ s.pid }}</td>
              <td class="px-5 py-2.5">
                <span v-if="s.outdated" class="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">{{ $t('claude.servers.outdated') }}</span>
                <span v-else class="badge bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">{{ $t('claude.servers.current') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="px-5 pb-5 text-sm text-zinc-500 dark:text-zinc-400">{{ $t('claude.servers.none') }}</p>
        <p class="border-t border-zinc-100 px-5 py-2.5 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          {{ $t('claude.servers.codeUpdated', { time: dateTime(status.code_updated_at) }) }}
        </p>
      </section>
    </div>
  </div>
</template>
