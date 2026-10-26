<script setup lang="ts">
import { Copy, Dices, FolderOpen, ImagePlus, LoaderCircle, Trash2, Upload, WandSparkles, X } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, historyImageUrl, isTauri, PROVIDER_NAMES, type GenerateResult, type ProviderName } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SizePicker from '../components/SizePicker.vue'
import StatusDot from '../components/StatusDot.vue'
import { basename } from '../format'
import { copyText, droppedFiles, onAppFileDrop, pickImages, revealPath } from '../platform'
import { localSizes } from '../sizes'
import { backendInfo, store, toast } from '../store'

const { t } = useI18n()
const form = reactive({
  backend: (store.cfg?.active_provider ?? 'openai') as ProviderName,
  size: '',
  n: 1,
  seed: '' as string | number,
  negative: '',
  strength: 0.6,
})
const pg = store.playground
const previews = reactive<Record<string, string>>({})
const results = ref<(GenerateResult & { prompt: string; at: number })[]>([])
const generating = ref(false)
const elapsed = ref(0)
const dragging = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
let stopDrop: (() => void) | undefined

const backends = computed(() => PROVIDER_NAMES.filter((n) => store.cfg?.providers[n].enabled))
const sizePresets = computed(() => [{ label: t('playground.sizeDefault'), value: '' }, ...localSizes(1024)])
const defaultSize = computed(() =>
  pg.inputs.length ? t('playground.sizeFromInput') : store.cfg?.providers[form.backend].default_size ?? '',
)

async function preview(path: string) {
  if (previews[path]) return
  try {
    previews[path] = (await api<{ data_url: string }>('/api/thumbnail', { method: 'POST', json: { path } })).data_url
  } catch {
    previews[path] = ''
  }
}
watch(() => [...pg.inputs], (paths) => paths.forEach(preview), { immediate: true })

function addInputs(paths: string[]) {
  for (const p of paths) if (!pg.inputs.includes(p)) pg.inputs.push(p)
}
async function choose() {
  try {
    addInputs(await pickImages())
  } catch (e) {
    toast((e as Error).message, 'error')
  }
}
async function onDrop(e: DragEvent) {
  dragging.value = false
  // The desktop app gets dropped files as paths through onAppFileDrop instead.
  if (e.dataTransfer?.files.length && !isTauri) addInputs(await droppedFiles(e))
}

async function generate() {
  if (!pg.prompt.trim() || generating.value) return
  generating.value = true
  elapsed.value = 0
  timer = setInterval(() => elapsed.value++, 1000)
  try {
    const result = await api<GenerateResult>('/api/generate', {
      method: 'POST',
      json: {
        prompt: pg.prompt.trim(),
        provider: form.backend,
        size: form.size || null,
        n: form.n,
        seed: form.seed === '' ? null : Number(form.seed),
        negative_prompt: form.negative.trim() || null,
        input_images: pg.inputs.length ? pg.inputs : null,
        strength: pg.inputs.length ? form.strength : null,
      },
    })
    results.value.unshift({ ...result, prompt: pg.prompt.trim(), at: Date.now() })
    toast(t('playground.done', { n: result.paths.length, s: elapsed.value }), 'success')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    clearInterval(timer)
    generating.value = false
  }
}

async function reveal(path: string) {
  if (!(await revealPath(path))) {
    await copyText(path)
    toast(t('common.pathCopied'))
  }
}
async function copy(path: string) {
  await copyText(path)
  toast(t('common.pathCopied'))
}

onMounted(async () => {
  stopDrop = await onAppFileDrop((paths) => {
    addInputs(paths)
    dragging.value = false
  })
})
onBeforeUnmount(() => {
  stopDrop?.()
  clearInterval(timer)
})
</script>

<template>
  <div v-if="store.cfg">
    <PageHeader :title="$t('nav.playground')" :subtitle="$t('playground.subtitle')" />

    <div class="grid items-start gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <!-- Request -->
      <section class="card space-y-5 p-5">
        <div>
          <label class="field-label">{{ $t('playground.prompt') }}</label>
          <textarea
            class="input min-h-28 resize-y leading-relaxed"
            v-model="pg.prompt"
            :placeholder="pg.inputs.length ? $t('playground.editPlaceholder') : $t('playground.promptPlaceholder')"
            @keydown.ctrl.enter="generate"
          />
        </div>

        <div>
          <label class="field-label">{{ $t('playground.backend') }}</label>
          <div class="flex items-center gap-2">
            <StatusDot :ok="backendInfo(form.backend)?.ok" />
            <select class="input" v-model="form.backend">
              <option v-for="n in backends" :key="n" :value="n">
                {{ $t(`backends.names.${n}`) }}{{ n === store.cfg.active_provider ? ` (${$t('common.active')})` : '' }}
              </option>
            </select>
          </div>
          <p class="hint truncate" :title="backendInfo(form.backend)?.detail">{{ backendInfo(form.backend)?.detail }}</p>
        </div>

        <div>
          <label class="field-label">{{ $t('playground.inputs') }}</label>
          <div
            :class="[
              'rounded-lg border-2 border-dashed p-3 transition',
              dragging ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-500/10' : 'border-zinc-200 dark:border-zinc-700',
            ]"
            @dragover.prevent="dragging = true"
            @dragleave="dragging = false"
            @drop.prevent="onDrop"
          >
            <div v-if="pg.inputs.length" class="mb-3 grid grid-cols-4 gap-2">
              <div v-for="(path, i) in pg.inputs" :key="path" class="group relative aspect-square overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-800" :title="path">
                <img v-if="previews[path]" :src="previews[path]" class="h-full w-full object-cover" alt="" />
                <span v-if="i === 0" class="badge absolute top-1 left-1 bg-indigo-600/90 text-white">{{ $t('playground.edited') }}</span>
                <button class="absolute top-1 right-1 rounded-full bg-zinc-900/70 p-0.5 text-white opacity-0 transition group-hover:opacity-100" @click="pg.inputs.splice(i, 1)">
                  <X class="h-3 w-3" />
                </button>
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button class="btn-secondary btn-sm" @click="choose"><ImagePlus class="h-3.5 w-3.5" /> {{ $t('playground.chooseFiles') }}</button>
              <button v-if="pg.inputs.length" class="btn-ghost btn-sm" @click="pg.inputs.splice(0)"><Trash2 class="h-3.5 w-3.5" /> {{ $t('playground.clearInputs') }}</button>
              <span class="flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400"><Upload class="h-3.5 w-3.5" /> {{ $t('playground.dropHint') }}</span>
            </div>
          </div>
          <p class="hint">{{ backendInfo(form.backend) ? `${$t('backends.imageInput')}: ${backendInfo(form.backend)!.image_input}` : '' }}</p>
        </div>

        <div>
          <label class="field-label">{{ $t('playground.size') }}</label>
          <SizePicker v-model="form.size" :presets="sizePresets" />
          <p class="hint">{{ $t('playground.sizeHint', { size: defaultSize }) }}</p>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="field-label">{{ $t('playground.count') }}</label>
            <div class="flex rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
              <button
                v-for="k in 4"
                :key="k"
                type="button"
                :class="['flex-1 rounded-md py-1 text-sm transition', form.n === k ? 'bg-indigo-600 text-white' : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800']"
                @click="form.n = k"
              >
                {{ k }}
              </button>
            </div>
          </div>
          <div>
            <label class="field-label">{{ $t('playground.seed') }}</label>
            <div class="flex gap-1.5">
              <input class="input" type="number" min="0" v-model="form.seed" :placeholder="$t('playground.seedRandom')" />
              <button class="btn-secondary shrink-0 px-2.5" :title="$t('playground.seedRoll')" @click="form.seed = Math.floor(Math.random() * 2 ** 31)">
                <Dices class="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <details class="group">
          <summary class="cursor-pointer text-[13px] font-medium text-zinc-600 select-none dark:text-zinc-400">{{ $t('playground.advanced') }}</summary>
          <div class="mt-4 space-y-4">
            <div>
              <label class="field-label">{{ $t('playground.negative') }}</label>
              <input class="input" v-model="form.negative" :placeholder="$t('playground.negativePlaceholder')" />
            </div>
            <div :class="!pg.inputs.length && 'opacity-50'">
              <label class="field-label">{{ $t('playground.strength') }}: {{ form.strength.toFixed(2) }}</label>
              <input class="w-full accent-indigo-600" type="range" min="0.05" max="1" step="0.05" v-model.number="form.strength" :disabled="!pg.inputs.length" />
              <p class="hint">{{ $t('playground.strengthHint') }}</p>
            </div>
          </div>
        </details>

        <button class="btn-primary w-full py-2.5" :disabled="!pg.prompt.trim() || generating" @click="generate">
          <LoaderCircle v-if="generating" class="h-4 w-4 animate-spin" />
          <WandSparkles v-else class="h-4 w-4" />
          {{ generating ? $t('playground.generating', { s: elapsed }) : pg.inputs.length ? $t('playground.edit') : $t('playground.generate') }}
        </button>
        <p class="hint -mt-2 text-center">{{ $t('playground.savedTo', { dir: store.meta?.playground_dir }) }}</p>
      </section>

      <!-- Results -->
      <section class="space-y-4">
        <div v-if="generating" class="card flex items-center gap-3 p-5 text-sm text-zinc-600 dark:text-zinc-300">
          <LoaderCircle class="h-5 w-5 animate-spin text-indigo-500" />
          {{ $t('playground.working', { backend: $t(`backends.names.${form.backend}`), s: elapsed }) }}
        </div>
        <div v-if="!results.length && !generating" class="card grid place-items-center px-6 py-20 text-center">
          <WandSparkles class="mb-3 h-8 w-8 text-zinc-300 dark:text-zinc-600" />
          <p class="font-medium">{{ $t('playground.emptyTitle') }}</p>
          <p class="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">{{ $t('playground.emptyText') }}</p>
        </div>
        <article v-for="r in results" :key="r.at" class="card overflow-hidden">
          <div :class="['grid gap-px bg-zinc-200 dark:bg-zinc-800', r.paths.length > 1 ? 'grid-cols-2' : '']">
            <img
              v-for="(path, i) in r.paths"
              :key="path"
              :src="r.history_id ? historyImageUrl(r.history_id, 'outputs', i) : ''"
              class="max-h-[32rem] w-full bg-zinc-100 object-contain dark:bg-zinc-950"
              :alt="r.prompt"
            />
          </div>
          <div class="space-y-2 p-4">
            <p class="text-sm leading-relaxed">{{ r.prompt }}</p>
            <p class="text-xs text-zinc-500 dark:text-zinc-400">{{ r.summary.replace(/:$/, '') }}</p>
            <div v-for="path in r.paths" :key="path" class="flex flex-wrap items-center gap-1.5 pt-1">
              <span class="mono min-w-0 flex-1 truncate text-zinc-500 dark:text-zinc-400" :title="path">{{ basename(path) }}</span>
              <button class="btn-ghost btn-sm" @click="reveal(path)"><FolderOpen class="h-3.5 w-3.5" /> {{ $t('common.showInFolder') }}</button>
              <button class="btn-ghost btn-sm" @click="copy(path)"><Copy class="h-3.5 w-3.5" /> {{ $t('common.copyPath') }}</button>
              <button class="btn-secondary btn-sm" @click="addInputs([path])"><ImagePlus class="h-3.5 w-3.5" /> {{ $t('playground.useAsInput') }}</button>
            </div>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>
