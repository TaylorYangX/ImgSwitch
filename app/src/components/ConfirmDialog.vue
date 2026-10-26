<script setup lang="ts">
import { store } from '../store'

function answer(ok: boolean) {
  store.confirm?.resolve(ok)
  store.confirm = null
}
</script>

<template>
  <Transition enter-from-class="opacity-0" leave-to-class="opacity-0" enter-active-class="transition" leave-active-class="transition">
    <div v-if="store.confirm" class="fixed inset-0 z-50 grid place-items-center bg-zinc-950/40 p-4" @click.self="answer(false)">
      <div class="card w-full max-w-md p-5 shadow-xl">
        <p class="text-sm leading-relaxed">{{ store.confirm.message }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <button class="btn-secondary" @click="answer(false)">{{ $t('common.cancel') }}</button>
          <button :class="store.confirm.danger ? 'btn btn-sm bg-red-600 px-3 py-2 text-sm text-white hover:bg-red-500' : 'btn-primary'" @click="answer(true)">
            {{ store.confirm.confirmLabel || $t('common.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
