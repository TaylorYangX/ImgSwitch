<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="mb-6 flex flex-wrap items-end justify-between gap-4">
    <div class="min-w-0">
      <h1 class="text-xl font-semibold tracking-tight">{{ title }}</h1>
      <p v-if="subtitle" class="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{{ subtitle }}</p>
    </div>
    <div class="flex items-center gap-2"><slot /></div>
  </header>
</template>
