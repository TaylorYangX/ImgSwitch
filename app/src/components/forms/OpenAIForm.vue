<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, type OpenAIConfig } from '../../api'
import { modelFamily, OPENAI_SIZES, openaiSizes } from '../../sizes'
import { store } from '../../store'
import SizePicker from '../SizePicker.vue'
import SecretField from './SecretField.vue'

const { t } = useI18n()
const p = computed(() => store.cfg!.providers.openai as OpenAIConfig)
// Shown until the account's real model list has loaded.
const FALLBACK_MODELS = ['dall-e-2', 'dall-e-3', 'gpt-image-1']

const models = ref<{ image: string[]; other: string[] } | null>(null)
const loading = ref(false)
const error = ref('')
const custom = ref(false)
let loadedFor = ''
let timer: ReturnType<typeof setTimeout> | undefined

const isGptImage = computed(() => modelFamily(p.value.model) === 'gpt-image')
const sizes = computed(() => openaiSizes(p.value.model))
const options = computed(() => {
  const list = !models.value ? FALLBACK_MODELS : models.value.image.length ? models.value.image : models.value.other
  return p.value.model && !list.includes(p.value.model) ? [p.value.model, ...list] : list
})
const choice = computed({
  get: () => (custom.value ? '__custom__' : p.value.model),
  set: (v: string) => {
    custom.value = v === '__custom__'
    if (!custom.value) p.value.model = v
  },
})
const hint = computed(() => {
  if (loading.value) return t('forms.openai.modelsLoading')
  if (error.value) return error.value
  if (!models.value) return p.value.api_key ? t('forms.openai.modelsRefresh') : t('forms.openai.modelsNeedKey')
  if (models.value.image.length) return t('forms.openai.modelsFound', { n: models.value.image.length })
  return t('forms.openai.modelsAll', { n: models.value.other.length })
})

async function loadModels() {
  loading.value = true
  error.value = ''
  try {
    models.value = await api('/api/openai/models', { method: 'POST', json: p.value })
    loadedFor = `${p.value.base_url}\n${p.value.api_key}`
  } catch (e) {
    error.value = t('forms.openai.modelsError', { error: (e as Error).message })
  } finally {
    loading.value = false
  }
}

// A size the newly chosen model doesn't support would make every call fail.
watch(
  () => p.value.model,
  (m) => {
    const family = modelFamily(m)
    if (family && !OPENAI_SIZES[family].includes(p.value.default_size)) p.value.default_size = '1024x1024'
  },
)
watch([() => p.value.base_url, () => p.value.api_key], ([base, key]) => {
  clearTimeout(timer)
  if (key && loadedFor !== `${base}\n${key}`) timer = setTimeout(loadModels, 600)
})
onMounted(() => p.value.api_key && loadModels())
</script>

<template>
  <div class="space-y-5">
    <div>
      <label class="field-label">{{ $t('forms.openai.baseUrl') }}</label>
      <input class="input mono" v-model.trim="p.base_url" placeholder="https://api.openai.com/v1" spellcheck="false" />
      <p class="hint">{{ $t('forms.openai.baseUrlHint') }}</p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.apiKey') }}</label>
      <SecretField v-model="p.api_key" placeholder="sk-…" />
      <p class="hint">
        {{ store.meta?.api_key_env_var ? $t('forms.openai.keyEnv', { name: store.meta.api_key_env_var }) : $t('forms.keyStored') }}
      </p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.openai.model') }}</label>
      <div class="flex gap-2">
        <select class="input mono" v-model="choice">
          <option v-for="m in options" :key="m" :value="m">{{ m }}</option>
          <option value="__custom__">{{ $t('forms.openai.customModel') }}</option>
        </select>
        <button type="button" class="btn-secondary shrink-0" :disabled="loading || !p.api_key" @click="loadModels">
          <RefreshCw :class="['h-4 w-4', loading && 'animate-spin']" />
        </button>
      </div>
      <input v-if="custom" class="input mono mt-2" v-model.trim="p.model" placeholder="flux-1-schnell" spellcheck="false" />
      <p :class="['hint', error && 'text-red-600! dark:text-red-400!']">{{ hint }}</p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.openai.responseFormat') }}</label>
      <select class="input" v-model="p.response_format" :disabled="isGptImage">
        <option value="b64_json">{{ $t('forms.openai.formatB64') }}</option>
        <option value="url">{{ $t('forms.openai.formatUrl') }}</option>
        <option value="omit">{{ $t('forms.openai.formatOmit') }}</option>
      </select>
      <p v-if="isGptImage" class="hint">{{ $t('forms.openai.gptImageNote') }}</p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.defaultSize') }}</label>
      <SizePicker v-model="p.default_size" :presets="sizes" />
    </div>
    <div class="max-w-48">
      <label class="field-label">{{ $t('forms.timeout') }}</label>
      <input class="input" type="number" min="1" v-model.number="p.timeout" />
    </div>
  </div>
</template>
