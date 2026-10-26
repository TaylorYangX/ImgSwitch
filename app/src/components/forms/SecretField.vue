<script setup lang="ts">
import { Eye, EyeOff } from '@lucide/vue'
import { ref } from 'vue'

defineProps<{ placeholder?: string }>()
const model = defineModel<string>({ required: true })
const show = ref(false)
</script>

<template>
  <div class="flex gap-2">
    <input
      class="input mono"
      :type="show ? 'text' : 'password'"
      v-model.trim="model"
      :placeholder="placeholder"
      autocomplete="off"
      spellcheck="false"
      @focus="($event.target as HTMLInputElement).select()"
    />
    <button type="button" class="btn-secondary shrink-0 px-2.5" :title="show ? $t('forms.hide') : $t('forms.show')" @click="show = !show">
      <EyeOff v-if="show" class="h-4 w-4" />
      <Eye v-else class="h-4 w-4" />
    </button>
  </div>
</template>
