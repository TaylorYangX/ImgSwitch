<script setup lang="ts">
defineProps<{ ok?: boolean | null }>()
</script>

<template>
  <span
    :class="[
      'inline-block h-2 w-2 shrink-0 rounded-full',
      ok == null ? 'bg-zinc-300 dark:bg-zinc-600' : ok ? 'bg-emerald-500 shadow-[0_0_0_3px] shadow-emerald-500/15' : 'bg-red-500',
    ]"
  />
</template>
