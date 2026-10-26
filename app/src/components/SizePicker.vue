<script setup lang="ts">
defineProps<{ presets: { label: string; value: string }[] }>()
const model = defineModel<string>({ required: true })
</script>

<template>
  <div>
    <div class="mb-2 flex flex-wrap gap-1.5">
      <button
        v-for="p in presets"
        :key="p.value"
        type="button"
        @click="model = p.value"
        :class="[
          'chip',
          model === p.value
            ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300'
            : 'border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-600',
        ]"
      >
        {{ p.label }}
      </button>
    </div>
    <input class="input mono" v-model.trim="model" placeholder="1024x1024" spellcheck="false" />
  </div>
</template>
