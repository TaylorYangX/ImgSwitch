import { i18n } from './i18n'

/** "3 minutes ago" style time, in the interface language. */
export function timeAgo(epochSeconds: number): string {
  const rtf = new Intl.RelativeTimeFormat(i18n.global.locale.value, { numeric: 'auto' })
  const seconds = Math.round(epochSeconds - Date.now() / 1000)
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit)
  }
  return rtf.format(seconds, 'second')
}

export function dateTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(i18n.global.locale.value)
}

export function basename(path: string): string {
  return path.split('/').pop() || path
}

/** /home/<user>/x → ~/x, so long folders stay readable in tight columns. */
export function shortPath(path: string): string {
  return path.replace(/^\/home\/[^/]+(?=\/|$)/, '~')
}
