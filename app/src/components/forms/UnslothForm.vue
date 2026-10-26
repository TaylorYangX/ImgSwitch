<script setup lang="ts">
import { computed } from 'vue'
import type { UnslothConfig } from '../../api'
import { store } from '../../store'
import LocalSizeField from './LocalSizeField.vue'
import SecretField from './SecretField.vue'

const p = computed(() => store.cfg!.providers.unsloth as UnslothConfig)

// An emptied optional number stores null ("use the model's default"), not '' which the config rejects.
function optionalNumber(e: Event): number | null {
  const value = (e.target as HTMLInputElement).value
  return value === '' ? null : Number(value)
}
</script>

<template>
  <div class="space-y-5">
    <div>
      <label class="field-label">{{ $t('forms.unsloth.url') }}</label>
      <input class="input mono" v-model.trim="p.base_url" placeholder="http://127.0.0.1:8888" spellcheck="false" />
      <p class="hint">{{ $t('forms.unsloth.urlHint') }}</p>
    </div>
    <div>
      <label class="field-label">{{ $t('forms.apiKey') }}</label>
      <SecretField v-model="p.api_key" placeholder="sk-unsloth-…" />
      <p class="hint">{{ $t('forms.unsloth.keyHint') }}</p>
    </div>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="field-label">{{ $t('forms.steps') }}</label>
        <input class="input" type="number" min="1" max="100" :placeholder="$t('forms.modelDefault')" :value="p.steps" @input="p.steps = optionalNumber($event)" />
        <p class="hint">{{ $t('forms.unsloth.emptyDefault') }}</p>
      </div>
      <div>
        <label class="field-label">{{ $t('forms.unsloth.guidance') }}</label>
        <input class="input" type="number" min="0" max="20" step="0.5" :placeholder="$t('forms.modelDefault')" :value="p.guidance" @input="p.guidance = optionalNumber($event)" />
        <p class="hint">{{ $t('forms.unsloth.guidanceHint') }}</p>
      </div>
    </div>
    <LocalSizeField v-model="p.default_size" />
    <div class="max-w-48">
      <label class="field-label">{{ $t('forms.timeout') }}</label>
      <input class="input" type="number" min="1" v-model.number="p.timeout" />
    </div>
  </div>
</template>
