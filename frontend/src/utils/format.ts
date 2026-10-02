// Presentation helpers for structured data (shared by Artifacts / Result views).

/**
 * Pretty-print a structured-data value for display inside a <pre> block.
 *
 * The Core stores some structured values as JSON *strings* (double-encoded).
 * Recursively unwrap any string that parses as JSON so users never see the
 * raw `"{\"phase\": ...}"` escapes from the screenshots.
 */
export function prettyJson(value: unknown, depth = 0): string {
  if (depth > 4) {
    // safety: very deep nesting is not useful at a glance
    return JSON.stringify(value, null, 2)
  }
  if (typeof value === 'string') {
    const unwrapped = tryParse(value)
    if (unwrapped !== null) return prettyJson(unwrapped, depth + 1)
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    const items = value.map((item) => prettyJson(item, depth + 1))
    if (items.length === 0) return '[]'
    return `[\n${items.map((item) => indent(item)).join(',\n')}\n]`
  }
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).map(
      ([key, val]) => `${JSON.stringify(key)}: ${prettyJson(val, depth + 1)}`,
    )
    if (entries.length === 0) return '{}'
    return `{\n${entries.map((entry) => indent(entry)).join(',\n')}\n}`
  }
  return JSON.stringify(value)
}

function indent(text: string): string {
  return text
    .split('\n')
    .map((line) => `  ${line}`)
    .join('\n')
}

/** Parse a string as JSON; returns null when it is plain text. */
function tryParse(raw: string): unknown | null {
  const trimmed = raw.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null
  try {
    return JSON.parse(trimmed) as unknown
  } catch {
    return null
  }
}

/**
 * Return the URL only when it is a safe, clickable http(s) link.
 * Anything else (empty, `javascript:`, relative, malformed) returns null so the
 * UI never renders a fake or unsafe link.
 */
export function safeHttpUrl(url: string | undefined | null): string | null {
  if (!url) return null
  const trimmed = url.trim()
  if (!/^https?:\/\//i.test(trimmed)) return null
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
    return parsed.toString()
  } catch {
    return null
  }
}

/** Display host for a URL, or empty string when it cannot be parsed. */
export function hostOf(url: string | undefined | null): string {
  const safe = safeHttpUrl(url)
  if (!safe) return ''
  try {
    return new URL(safe).host
  } catch {
    return ''
  }
}

/** Keep the start and end of a long string visible (for URLs). */
export function truncateMiddle(text: string, max = 72): string {
  if (!text || text.length <= max) return text
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${text.slice(0, head)}…${text.slice(-tail)}`
}