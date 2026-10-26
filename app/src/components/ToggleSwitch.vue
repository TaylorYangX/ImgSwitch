<script setup lang="ts">
defineProps<{ disabled?: boolean; label?: string }>()
const model = defineModel<boolean>({ required: true })
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="model"
    :aria-label="label"
    :disabled="disabled"
    @click="model = !model"
    :class="[
      'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50',
      model ? 'bg-indigo-600' : 'bg-zinc-300 dark:bg-zinc-700',
    ]"
  >
    <span :class="['inline-block h-4 w-4 rounded-full bg-white shadow transition', model ? 'translate-x-4.5' : 'translate-x-0.5']" />
  </button>
</template>
