// Talks to the Python backend: the same origin in a browser, or the port the desktop app started it on.
import { invoke } from '@tauri-apps/api/core'

export const isTauri = '__TAURI_INTERNALS__' in window

let base = ''

/** Resolve where the backend lives. In the app this waits until the backend the app started is listening. */
export async function initApi(): Promise<void> {
  if (isTauri) base = await invoke<string>('backend_url')
}

export function apiUrl(path: string): string {
  return base + path
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export async function api<T = unknown>(path: string, options: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...init } = options
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: json === undefined ? init.headers : { 'Content-Type': 'application/json', ...init.headers },
    body: json === undefined ? init.body : JSON.stringify(json),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail
    const message = Array.isArray(detail)
      ? detail.map((e: { loc: string[]; msg: string }) => `${e.loc.filter((x) => x !== 'body').join('.')}: ${e.msg}`).join('; ')
      : String(detail || response.statusText)
    throw new ApiError(message, response.status)
  }
  return body as T
}

// ---- Types mirroring imgswitch/config.py and the API ------------------------------------------

export type ProviderName = 'openai' | 'a1111' | 'comfyui' | 'unsloth'
export const PROVIDER_NAMES: ProviderName[] = ['openai', 'a1111', 'comfyui', 'unsloth']

interface BaseProvider {
  enabled: boolean
  default_size: string
  timeout: number
  base_url: string
}
export interface OpenAIConfig extends BaseProvider {
  api_key: string
  model: string
  response_format: 'b64_json' | 'url' | 'omit'
}
export interface A1111Config extends BaseProvider {
  steps: number
  cfg_scale: number
  sampler_name: string
}
export interface ComfyUIConfig extends BaseProvider {
  workflow_path: string
  edit_workflow_path: string
  checkpoint: string
  steps: number
  cfg_scale: number
}
export interface UnslothConfig extends BaseProvider {
  api_key: string
  steps: number | null
  guidance: number | null
}
export interface Config {
  active_provider: ProviderName
  output: { dir: string; return_inline: boolean; inline_max_px: number; playground_dir: string }
  providers: { openai: OpenAIConfig; a1111: A1111Config; comfyui: ComfyUIConfig; unsloth: UnslothConfig }
  ui: { language: 'en' | 'zh-CN'; theme: 'system' | 'light' | 'dark' }
}

export interface Meta {
  version: string
  project_root: string
  config_path: string
  data_dir: string
  history_path: string
  playground_dir: string
  python: string
  app_mode: boolean
  wsl: boolean
  api_key_env_var: string | null
  claude_command: string
}

export interface HealthStatus {
  ok: boolean
  detail: string
  latency_ms: number | null
}

export interface BackendInfo extends HealthStatus {
  name: ProviderName
  label: string
  description: string
  enabled: boolean
  active: boolean
  image_input: string
}

export interface HistoryEntry {
  id: string
  time: number
  source?: string // 'playground', or the agent that asked: 'claude', 'codex', 'opencode', 'antigravity', …
  client?: string | null
  backend?: ProviderName
  backend_label?: string
  model?: string
  prompt?: string
  negative_prompt?: string | null
  width?: number
  height?: number
  seed?: number | null
  n?: number
  strength?: number | null
  inputs?: string[]
  outputs?: string[]
  cwd?: string
  missing?: boolean[]
}

export interface GenerateResult {
  summary: string
  history_id: string | null
  paths: string[]
  width: number
  height: number
  backend: ProviderName
  model: string
}

export type AgentKey = 'claude' | 'codex' | 'opencode' | 'antigravity'
export const AGENT_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  opencode: 'OpenCode',
  antigravity: 'Antigravity',
  gemini: 'Gemini CLI',
}

export interface Registration {
  where: string // 'user', 'local:<folder>' (Claude Code), or the config file it's in
  command: string
  args: string[]
  url: string | null
  command_exists: boolean
  points_here: boolean
}

export interface AgentStatus {
  key: AgentKey
  label: string
  installed: boolean
  config_path: string
  registrations: Registration[]
  registered: boolean
  snippet: string
  permissions?: { settings_path: string; allowed: Record<string, boolean> } // Claude Code only
}

export interface RunningServer {
  pid: number
  agent: string | null
  cwd: string
  transport: string
  started_at: number
  outdated: boolean
}

export interface AgentsStatus {
  agents: AgentStatus[]
  servers: RunningServer[]
  code_updated_at: number
}

export function historyImageUrl(id: string, kind: 'outputs' | 'inputs', index: number, thumb = false): string {
  return apiUrl(`/api/history/${id}/${kind}/${index}${thumb ? '?thumb=1' : ''}`)
}
