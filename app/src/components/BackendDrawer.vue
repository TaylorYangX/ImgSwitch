<script setup lang="ts">
import { PlugZap } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { api, type HealthStatus } from '../api'
import { backendInfo, store } from '../store'
import A1111Form from './forms/A1111Form.vue'
import ComfyUIForm from './forms/ComfyUIForm.vue'
import OpenAIForm from './forms/OpenAIForm.vue'
import UnslothForm from './forms/UnslothForm.vue'
import SideDrawer from './SideDrawer.vue'
import StatusDot from './StatusDot.vue'

const forms = { openai: OpenAIForm, a1111: A1111Form, comfyui: ComfyUIForm, unsloth: UnslothForm }
const name = computed(() => store.editing)
const result = ref<HealthStatus | null>(null)
const testing = ref(false)

watch(name, () => (result.value = null))

async function test() {
  if (!name.value) return
  testing.value = true
  try {
    result.value = await api<HealthStatus>(`/api/providers/${name.value}/test`, { method: 'POST', json: store.cfg!.providers[name.value] })
  } catch (e) {
    result.value = { ok: false, detail: (e as Error).message, latency_ms: null }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <SideDrawer
    :open="!!name"
    :title="name ? $t('backends.editTitle', { name: $t(`backends.names.${name}`) }) : ''"
    :subtitle="name ? backendInfo(name)?.description : ''"
    @close="store.editing = null"
  >
    <component :is="forms[name]" v-if="name && store.cfg" />
    <template #footer>
      <div class="flex items-center gap-3">
        <button class="btn-primary" :disabled="testing" @click="test">
          <PlugZap class="h-4 w-4" /> {{ testing ? $t('common.testing') : $t('backends.testConnection') }}
        </button>
        <p v-if="result" class="flex min-w-0 items-center gap-2 text-xs">
          <StatusDot :ok="result.ok" />
          <span :class="['truncate', result.ok ? 'text-zinc-600 dark:text-zinc-300' : 'text-red-600 dark:text-red-400']" :title="result.detail">
            {{ result.detail }}<template v-if="result.latency_ms != null"> · {{ result.latency_ms }} ms</template>
          </span>
        </p>
        <span class="ml-auto text-xs text-zinc-500 dark:text-zinc-400">{{ $t('backends.autosave') }}</span>
      </div>
    </template>
  </SideDrawer>
</template>
