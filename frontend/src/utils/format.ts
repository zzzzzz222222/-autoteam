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