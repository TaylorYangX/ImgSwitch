<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, type ComfyUIConfig } from '../../api'
import { store } from '../../store'
import LocalSizeField from './LocalSizeField.vue'

const { t } = useI18n()
const p = computed(() => store.cfg!.providers.comfyui as ComfyUIConfig)
const checkpoints = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const options = computed(() =>
  p.value.checkpoint && !checkpoints.value.includes(p.value.checkpoint) ? [p.value.checkpoint, ...checkpoints.value] : checkpoints.value,
)
const placeholders = ['prompt', 'negative_prompt', 'width', 'height', 'steps', 'cfg', 'seed', 'checkpoint', 'batch_size']
  .map((x) => `{{${x}}}`)
  .join(' ')

async function loadCheckpoints() {
  loading.value = true
  error.value = ''
  try {
    checkpoints.value = await api<string[]>('/api/comfyui/checkpoints', { method: 'POST', json: p.value })
    if (!checkpoints.value.length) error.value = t('forms.comfyui.noCheckpoints')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <div>
      <label class="field-label">{{ $t('forms.comfyui.url') }}</label>
      <input class="input mono" v-model.trim="p.base_url" placeholder="http://127.0.0.1:8188" spellcheck="false" />
    </div>
    <div>
      <label class="field-label">{{ $t('forms.comfyui.checkpoint') }}</label>
      <div class="flex gap-2">
        <select class="input" v-model="p.checkpoint">
          <option value="">{{ $t('forms.comfyui.firstCheckpoint') }}</option>
          <option v-for="c in options" :key="c" :value="c">{{ c }}</option>
        </select>
        <button type="button" class="btn-secondary shrink-0" :disabled="loading" @click="loadCheckpoints">
          <RefreshCw :class="['h-4 w-4', loading && 'animate-spin']" /> {{ $t('forms.comfyui.loadList') }}
        </button>
      </div>
      <p :class="['hint', error && 'text-red-600! dark:text-red-400!']">{{ error || $t('forms.comfyui.checkpointHint') }}</p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.comfyui.workflow') }}</label>
      <input class="input mono" v-model.trim="p.workflow_path" spellcheck="false" />
      <p class="hint">{{ $t('forms.comfyui.workflowHint') }} <span class="mono">{{ placeholders }}</span></p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.comfyui.editWorkflow') }}</label>
      <input class="input mono" v-model.trim="p.edit_workflow_path" spellcheck="false" />
      <p class="hint">{{ $t('forms.comfyui.editWorkflowHint') }} <span class="mono" v-pre>{{image}} {{denoise}}</span></p>
    </div>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="field-label">{{ $t('forms.steps') }}: {{ p.steps }}</label>
        <input class="mt-2 w-full accent-indigo-600" type="range" min="1" max="150" v-model.number="p.steps" />
      </div>
      <div>
        <label class="field-label">{{ $t('forms.cfgScale') }}</label>
        <input class="input" type="number" min="1" max="30" step="0.5" v-model.number="p.cfg_scale" />
      </div>
    </div>
    <LocalSizeField v-model="p.default_size" />
    <div class="max-w-48">
      <label class="field-label">{{ $t('forms.timeout') }}</label>
      <input class="input" type="number" min="1" v-model.number="p.timeout" />
    </div>
  </div>
</template>
