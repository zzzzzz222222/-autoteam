// Minimal, self-contained, XSS-safe Markdown -> HTML renderer (no dependency).
//
// Security model: every piece of input text is HTML-escaped *before* any markup
// is added, and the only tags ever emitted are the ones below. Raw HTML in the
// source can therefore never survive. Links are only emitted for safe http(s)
// URLs (`javascript:`, `data:`, relative or malformed URLs render as plain
// text). Inline formatting is applied to already-escaped text.
import { safeHttpUrl } from '@/utils/format'

const CODE_OPEN = '\uE000'
const CODE_CLOSE = '\uE001'
const LINK_OPEN = '\uE002'
const LINK_CLOSE = '\uE003'

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(raw: string): string {
  const codes: string[] = []
  const links: { label: string; url: string }[] = []

  // 1. pull out code spans and links so markdown chars inside them are inert
  let text = raw.replace(/`([^`]+)`/g, (_m, code: string) => {
    codes.push(escapeHtml(code))
    return `${CODE_OPEN}${codes.length - 1}${CODE_CLOSE}`
  })
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, url: string) => {
    links.push({ label, url })
    return `${LINK_OPEN}${links.length - 1}${LINK_CLOSE}`
  })

  // 2. escape everything that remains (no raw HTML can pass through)
  text = escapeHtml(text)

  // 3. inline emphasis on the escaped text
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
  text = text.replace(/(^|[^\w_])_([^_\n]+)_(?![\w_])/g, '$1<em>$2</em>')

  // 4. restore links (only safe http/https get an anchor)
  text = text.replace(
    new RegExp(`${LINK_OPEN}(\\d+)${LINK_CLOSE}`, 'g'),
    (_m, index: string) => {
      const link = links[Number(index)]
      if (!link) return ''
      const label = escapeHtml(link.label)
      const safe = safeHttpUrl(link.url)
      if (!safe) return label
      return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${label}</a>`
    },
  )

  // 5. restore code spans
  text = text.replace(
    new RegExp(`${CODE_OPEN}(\\d+)${CODE_CLOSE}`, 'g'),
    (_m, index: string) => `<code>${codes[Number(index)] ?? ''}</code>`,
  )
  return text
}

/** Render a trusted-shape, untrusted-content Markdown string to safe HTML. */
export function renderMarkdown(source: string): string {
  const lines = (source || '').replace(/\r\n?/g, '\n').split('\n')
  const out: string[] = []
  let paragraph: string[] = []
  let listType: 'ul' | 'ol' | null = null

  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${paragraph.map(renderInline).join('<br/>')}</p>`)
      paragraph = []
    }
  }
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    // fenced code block
    const fence = line.match(/^\s*(`{3,}|~{3,})\s*[\w+-]*\s*$/)
    if (fence) {
      flushParagraph()
      closeList()
      const mark = fence[1][0]
      const closer = new RegExp(`^\\s*${mark}{3,}\\s*$`)
      const buffer: string[] = []
      i += 1
      while (i < lines.length && !closer.test(lines[i])) {
        buffer.push(lines[i])
        i += 1
      }
      i += 1 // skip closing fence (or end of input)
      out.push(`<pre><code>${escapeHtml(buffer.join('\n'))}</code></pre>`)
      continue
    }

    // heading h1-h4
    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      flushParagraph()
      closeList()
      const level = heading[1].length
      out.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`)
      i += 1
      continue
    }

    // horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph()
      closeList()
      out.push('<hr/>')
      i += 1
      continue
    }

    // blockquote (rendered recursively)
    if (/^\s*>\s?/.test(line)) {
      flushParagraph()
      closeList()
      const buffer: string[] = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buffer.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      out.push(`<blockquote>${renderMarkdown(buffer.join('\n'))}</blockquote>`)
      continue
    }

    // unordered list
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) {
      flushParagraph()
      if (listType !== 'ul') {
        closeList()
        out.push('<ul>')
        listType = 'ul'
      }
      out.push(`<li>${renderInline(bullet[1])}</li>`)
      i += 1
      continue
    }

    // ordered list
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (numbered) {
      flushParagraph()
      if (listType !== 'ol') {
        closeList()
        out.push('<ol>')
        listType = 'ol'
      }
      out.push(`<li>${renderInline(numbered[1])}</li>`)
      i += 1
      continue
    }

    // blank line ends the current block
    if (!line.trim()) {
      flushParagraph()
      closeList()
      i += 1
      continue
    }

    paragraph.push(line)
    i += 1
  }

  flushParagraph()
  closeList()
  return out.join('\n')
}
