<script setup lang="ts">
import { CircleAlert, CircleCheck, Info } from '@lucide/vue'
import { store } from '../store'
</script>

<template>
  <div class="pointer-events-none fixed right-4 bottom-4 z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
    <TransitionGroup
      enter-from-class="translate-y-2 opacity-0"
      leave-to-class="opacity-0"
      enter-active-class="transition duration-200"
      leave-active-class="transition duration-200"
    >
      <div
        v-for="t in store.toasts"
        :key="t.id"
        class="card pointer-events-auto flex items-start gap-2.5 px-3.5 py-3 text-sm shadow-lg"
      >
        <CircleCheck v-if="t.kind === 'success'" class="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        <CircleAlert v-else-if="t.kind === 'error'" class="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        <Info v-else class="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
        <span class="break-words">{{ t.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>
