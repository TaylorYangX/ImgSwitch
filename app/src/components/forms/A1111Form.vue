<script setup lang="ts">
import { computed } from 'vue'
import type { A1111Config } from '../../api'
import { store } from '../../store'
import LocalSizeField from './LocalSizeField.vue'

const p = computed(() => store.cfg!.providers.a1111 as A1111Config)
const samplers = ['Euler a', 'Euler', 'DPM++ 2M', 'DPM++ 2M SDE', 'DPM++ SDE', 'DDIM', 'UniPC', 'LMS', 'Heun']
</script>

<template>
  <div class="space-y-5">
    <div>
      <label class="field-label">{{ $t('forms.a1111.url') }}</label>
      <input class="input mono" v-model.trim="p.base_url" placeholder="http://127.0.0.1:7860" spellcheck="false" />
      <p class="hint">{{ $t('forms.a1111.urlHint') }}</p>
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
      <div>
        <label class="field-label">{{ $t('forms.a1111.sampler') }}</label>
        <input class="input" v-model.trim="p.sampler_name" list="a1111-samplers" />
        <datalist id="a1111-samplers"><option v-for="s in samplers" :key="s" :value="s" /></datalist>
      </div>
      <div>
        <label class="field-label">{{ $t('forms.timeout') }}</label>
        <input class="input" type="number" min="1" v-model.number="p.timeout" />
      </div>
    </div>
    <LocalSizeField v-model="p.default_size" />
  </div>
</template>
