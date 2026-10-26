// Size presets: OpenAI models accept fixed sizes; local models take any multiple of 64 around a base resolution.
const RATIOS: [string, number, number][] = [
  ['1:1', 1, 1], ['4:3', 4, 3], ['3:4', 3, 4], ['3:2', 3, 2], ['2:3', 2, 3], ['16:9', 16, 9], ['9:16', 9, 16],
]

export function localSizes(base: number): { label: string; value: string }[] {
  return RATIOS.map(([label, a, b]) => {
    const r = Math.sqrt(a / b)
    const w = Math.round((base * r) / 64) * 64
    const h = Math.round(base / r / 64) * 64
    return { label: `${label} · ${w}×${h}`, value: `${w}x${h}` }
  })
}

export const OPENAI_SIZES: Record<string, string[]> = {
  'dall-e-2': ['256x256', '512x512', '1024x1024'],
  'dall-e-3': ['1024x1024', '1792x1024', '1024x1792'],
  'gpt-image': ['1024x1024', '1536x1024', '1024x1536'],
}

export function modelFamily(model: string): string | null {
  if (/gpt-image|chatgpt-image/i.test(model)) return 'gpt-image'
  if (/dall-e-3/i.test(model)) return 'dall-e-3'
  if (/dall-e-2/i.test(model)) return 'dall-e-2'
  return null
}

export function openaiSizes(model: string): { label: string; value: string }[] {
  const family = modelFamily(model)
  const sizes = family ? OPENAI_SIZES[family] : [...new Set(Object.values(OPENAI_SIZES).flat())]
  return sizes.map((s) => ({ label: s.replace('x', '×'), value: s }))
}
