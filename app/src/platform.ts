// Things only the desktop app can do natively, each with a browser fallback.
import { invoke } from '@tauri-apps/api/core'
import { api, isTauri } from './api'

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tif', 'tiff']

async function uploadFiles(files: File[]): Promise<string[]> {
  const paths: string[] = []
  for (const file of files) {
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
    const { path } = await api<{ path: string }>('/api/uploads', { method: 'POST', json: { name: file.name, data } })
    paths.push(path)
  }
  return paths
}

/** Let the user choose image files and return their paths (uploaded first in a browser). */
export async function pickImages(): Promise<string[]> {
  if (isTauri) {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const chosen = await open({ multiple: true, filters: [{ name: 'Images', extensions: IMAGE_EXTENSIONS }] })
    return chosen === null ? [] : Array.isArray(chosen) ? chosen : [chosen]
  }
  const files = await new Promise<File[]>((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.accept = IMAGE_EXTENSIONS.map((e) => `.${e}`).join(',')
    input.onchange = () => resolve(Array.from(input.files ?? []))
    input.click()
  })
  return uploadFiles(files)
}

/** Paths for files dropped in a browser (the desktop app gets paths from onAppFileDrop instead). */
export function droppedFiles(event: DragEvent): Promise<string[]> {
  const files = Array.from(event.dataTransfer?.files ?? []).filter((f) => f.type.startsWith('image/'))
  return uploadFiles(files)
}

/** In the desktop app, call `handler` with the paths of image files dropped on the window. */
export async function onAppFileDrop(handler: (paths: string[]) => void): Promise<() => void> {
  if (!isTauri) return () => {}
  const { getCurrentWebview } = await import('@tauri-apps/api/webview')
  return getCurrentWebview().onDragDropEvent((event) => {
    if (event.payload.type === 'drop') {
      handler(event.payload.paths.filter((p) => IMAGE_EXTENSIONS.includes(p.split('.').pop()?.toLowerCase() ?? '')))
    }
  })
}

export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // WebKitGTK may refuse the async clipboard; fall back to a hidden textarea.
    const area = document.createElement('textarea')
    area.value = text
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
}

/** Show a file in the file manager (Windows Explorer under WSL). Returns false where that isn't possible. */
export async function revealPath(path: string): Promise<boolean> {
  if (!isTauri) return false
  await invoke('reveal_path', { path })
  return true
}

/** Open a file or folder with its default app. Returns false where that isn't possible. */
export async function openPath(path: string): Promise<boolean> {
  if (!isTauri) return false
  await invoke('open_path', { path })
  return true
}
