<script setup lang="ts">
import { CircleCheck, Copy, RefreshCw, ShieldCheck, TriangleAlert } from '@lucide/vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AGENT_LABELS, api, type AgentKey, type AgentsStatus, type AgentStatus, type Registration } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { basename, dateTime, shortPath, timeAgo } from '../format'
import { copyText } from '../platform'
import { toast } from '../store'

const { t } = useI18n()
const status = ref<AgentsStatus | null>(null)
const loading = ref(false)
const busy = reactive<Record<string, boolean>>({})

// Each agent's colour, for its initial badge.
const ACCENTS: Record<AgentKey, string> = {
  claude: 'bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300',
  codex: 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900',
  opencode: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  antigravity: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300',
}
const outdated = computed(() => status.value?.servers.filter((s) => s.outdated).length ?? 0)

function where(r: Registration): string {
  if (r.where === 'user') return t('agents.where.user')
  if (r.where.startsWith('local:')) return `${t('agents.where.local')} · ${shortPath(r.where.slice(6))}`
  return basename(r.where) // the config file; its full path is shown above
}

async function load() {
  loading.value = true
  try {
    status.value = await api<AgentsStatus>('/api/agents')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    loading.value = false
  }
}

async function register(agent: AgentStatus) {
  busy[agent.key] = true
  try {
    const r = await api<{ ok: boolean; output: string }>(`/api/agents/${agent.key}/register`, { method: 'POST' })
    if (r.ok) toast(`${t('agents.registered_done', { agent: agent.label })} ${t(`agents.reload.${agent.key}`)}`, 'success')
    else toast(r.output, 'error')
    await load()
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    busy[agent.key] = false
  }
}

async function allowClaudeTools() {
  busy.permissions = true
  try {
    await api('/api/agents/claude/permissions', { method: 'POST' })
    toast(t('agents.permissions.done'), 'success')
    await load()
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    busy.permissions = false
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
    <PageHeader :title="$t('nav.agents')" :subtitle="$t('agents.subtitle')">
      <button class="btn-secondary" :disabled="loading" @click="load">
        <RefreshCw :class="['h-4 w-4', loading && 'animate-spin']" /> {{ $t('common.refresh') }}
      </button>
    </PageHeader>

    <div v-if="status" class="space-y-5">
      <div class="grid gap-4 xl:grid-cols-2">
        <article v-for="agent in status.agents" :key="agent.key" :class="['card flex flex-col', !agent.installed && 'opacity-70']">
          <div class="flex items-start gap-4 p-5">
            <div :class="['grid h-10 w-10 shrink-0 place-items-center rounded-xl text-base font-bold', ACCENTS[agent.key]]">
              {{ agent.label[0] }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="text-[15px] font-semibold">{{ agent.label }}</h2>
                <span
                  :class="[
                    'badge',
                    agent.registered
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                      : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
                  ]"
                >
                  <CircleCheck v-if="agent.registered" class="h-3 w-3" />
                  {{ agent.registered ? $t('agents.registered') : $t('agents.notRegistered') }}
                </span>
                <span v-if="!agent.installed" class="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                  {{ $t('agents.notInstalled') }}
                </span>
              </div>
              <p class="mt-1 flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                <span class="shrink-0">{{ $t('agents.config') }}:</span>
                <span class="mono truncate" :title="agent.config_path">{{ shortPath(agent.config_path) }}</span>
              </p>

              <ul v-if="agent.registrations.length" class="mt-3 space-y-1.5">
                <li v-for="r in agent.registrations" :key="r.where" class="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-950">
                  <p class="flex flex-wrap items-center gap-2 text-xs">
                    <span class="font-medium text-zinc-700 dark:text-zinc-300">{{ where(r) }}</span>
                    <span v-if="!r.command_exists" class="badge bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300">{{ $t('agents.commandMissing') }}</span>
                    <span v-else-if="!r.points_here" class="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">{{ $t('agents.otherCopy') }}</span>
                  </p>
                  <p class="mono mt-1 truncate text-zinc-500 dark:text-zinc-400" :title="r.url ?? [r.command, ...r.args].join(' ')">
                    {{ r.url ?? [r.command, ...r.args].map(shortPath).join(' ') }}
                  </p>
                </li>
              </ul>

              <p class="hint">{{ $t(`agents.reload.${agent.key}`) }}</p>

              <!-- Claude Code's tool permissions -->
              <div v-if="agent.permissions" class="mt-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <p class="flex items-center gap-1.5 text-[13px] font-medium">
                  <ShieldCheck class="h-4 w-4 text-zinc-400" /> {{ $t('agents.permissions.title') }}
                </p>
                <p class="hint mt-0.5">{{ $t('agents.permissions.desc') }}</p>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <span
                    v-for="(ok, tool) in agent.permissions.allowed"
                    :key="tool"
                    :class="['badge', ok ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400']"
                    :title="String(tool)"
                  >
                    {{ String(tool).replace('mcp__imgswitch__', '') }}: {{ ok ? $t('agents.permissions.allowed') : $t('agents.permissions.asks') }}
                  </span>
                  <button
                    v-if="!Object.values(agent.permissions.allowed).every(Boolean)"
                    class="btn-secondary btn-sm"
                    :disabled="busy.permissions"
                    @click="allowClaudeTools"
                  >
                    {{ $t('agents.permissions.allow') }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <footer class="mt-auto flex flex-wrap items-center gap-2 border-t border-zinc-100 px-5 py-3 dark:border-zinc-800">
            <details class="min-w-0 flex-1">
              <summary class="cursor-pointer text-xs text-zinc-500 select-none dark:text-zinc-400">{{ $t('agents.showConfig') }}</summary>
              <div class="relative mt-2">
                <pre class="mono max-h-48 overflow-auto rounded-lg bg-zinc-900 p-3 pr-10 text-zinc-100 dark:bg-black">{{ agent.snippet }}</pre>
                <button class="btn-ghost btn-sm absolute top-1.5 right-1.5 text-zinc-300 hover:bg-zinc-800" @click="copy(agent.snippet)">
                  <Copy class="h-3.5 w-3.5" />
                </button>
              </div>
            </details>
            <button v-if="!agent.registered" class="btn-primary btn-sm self-start" :disabled="busy[agent.key]" @click="register(agent)">
              {{ $t('agents.register') }}
            </button>
          </footer>
        </article>
      </div>

      <!-- Running servers -->
      <section class="card overflow-hidden">
        <div class="flex items-start gap-3 p-5 pb-3">
          <TriangleAlert v-if="outdated" class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
          <CircleCheck v-else class="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
          <div>
            <h2 class="font-semibold">{{ $t('agents.servers.title') }}</h2>
            <p class="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
              {{ outdated ? $t('agents.servers.outdatedHint', { n: outdated }) : $t('agents.servers.desc') }}
            </p>
          </div>
        </div>
        <table v-if="status.servers.length" class="w-full table-fixed text-sm">
          <thead class="border-y border-zinc-100 bg-zinc-50 text-left text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
            <tr>
              <th class="w-36 px-5 py-2 font-medium">{{ $t('agents.servers.agent') }}</th>
              <th class="px-3 py-2 font-medium">{{ $t('agents.servers.folder') }}</th>
              <th class="w-32 px-3 py-2 font-medium">{{ $t('agents.servers.started') }}</th>
              <th class="w-20 px-3 py-2 font-medium">PID</th>
              <th class="w-44 px-5 py-2 font-medium">{{ $t('agents.servers.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in status.servers" :key="s.pid" class="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
              <td class="px-5 py-2.5 font-medium">{{ s.agent ? (AGENT_LABELS[s.agent] ?? s.agent) : $t('agents.servers.unknown') }}</td>
              <td class="mono truncate px-3 py-2.5" :title="s.cwd">{{ shortPath(s.cwd) }}</td>
              <td class="px-3 py-2.5 whitespace-nowrap text-zinc-600 dark:text-zinc-400" :title="dateTime(s.started_at)">{{ timeAgo(s.started_at) }}</td>
              <td class="mono px-3 py-2.5 text-zinc-500">{{ s.pid }}</td>
              <td class="px-5 py-2.5">
                <span v-if="s.outdated" class="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">{{ $t('agents.servers.outdated') }}</span>
                <span v-else class="badge bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">{{ $t('agents.servers.current') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="px-5 pb-5 text-sm text-zinc-500 dark:text-zinc-400">{{ $t('agents.servers.none') }}</p>
        <p class="border-t border-zinc-100 px-5 py-2.5 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          {{ $t('agents.servers.codeUpdated', { time: dateTime(status.code_updated_at) }) }}
        </p>
      </section>
    </div>
  </div>
</template>
