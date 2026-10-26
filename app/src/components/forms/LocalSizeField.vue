<script setup lang="ts">
import { computed, ref } from 'vue'
import { localSizes } from '../../sizes'
import SizePicker from '../SizePicker.vue'

const model = defineModel<string>({ required: true })
const base = ref(1024)
const presets = computed(() => localSizes(base.value))
</script>

<template>
  <div>
    <label class="field-label">{{ $t('forms.defaultSize') }}</label>
    <div class="mb-2 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
      <span>{{ $t('forms.baseResolution') }}</span>
      <select class="input w-auto! py-1! text-xs" v-model.number="base">
        <option :value="512">512 (SD 1.5)</option>
        <option :value="768">768 (SD 2.x)</option>
        <option :value="1024">1024 (SDXL / Flux / Qwen)</option>
      </select>
    </div>
    <SizePicker v-model="model" :presets="presets" />
  </div>
</template>
