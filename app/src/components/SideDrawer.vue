<script setup lang="ts">
import { X } from '@lucide/vue'

defineProps<{ open: boolean; title: string; subtitle?: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <Transition enter-from-class="opacity-0" leave-to-class="opacity-0" enter-active-class="transition" leave-active-class="transition">
    <div v-if="open" class="fixed inset-0 z-40 bg-zinc-950/30" @click="emit('close')" />
  </Transition>
  <Transition
    enter-from-class="translate-x-full"
    leave-to-class="translate-x-full"
    enter-active-class="transition duration-200 ease-out"
    leave-active-class="transition duration-150 ease-in"
  >
    <aside
      v-if="open"
      :class="[
        'fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-900',
        wide ? 'max-w-3xl' : 'max-w-xl',
      ]"
    >
      <header class="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <div class="min-w-0">
          <h2 class="truncate text-base font-semibold">{{ title }}</h2>
          <p v-if="subtitle" class="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">{{ subtitle }}</p>
        </div>
        <button class="btn-ghost -mr-2 p-1.5" :aria-label="$t('common.close')" @click="emit('close')"><X class="h-4 w-4" /></button>
      </header>
      <div class="flex-1 overflow-y-auto px-6 py-5"><slot /></div>
      <footer v-if="$slots.footer" class="border-t border-zinc-200 px-6 py-3 dark:border-zinc-800"><slot name="footer" /></footer>
    </aside>
  </Transition>
</template>
