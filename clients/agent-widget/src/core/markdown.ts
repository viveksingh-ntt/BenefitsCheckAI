import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const marked = new Marked({ gfm: true, breaks: true, async: false });

const ALLOWED_TAGS = ['p', 'br', 'strong', 'b', 'em', 'i', 'a', 'ul', 'ol', 'li', 'code', 'span'];
const ALLOWED_ATTR = ['href', 'title', 'target', 'rel'];
const SAFE_LINK = /^(https:|mailto:|tel:|\/(?!\/))/i;

let hooked = false;
function ensureHooks(): void {
  if (hooked) return;
  hooked = true;
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node instanceof Element && node.tagName === 'A') {
      const href = node.getAttribute('href') ?? '';
      if (!SAFE_LINK.test(href)) {
        node.removeAttribute('href');
      } else if (/^https:/i.test(href)) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
      }
    }
  });
}

/**
 * Renders agent markdown to sanitized HTML. Agents can never inject raw HTML, scripts,
 * images or styles: only basic formatting, lists and safe links survive.
 */
export function renderMarkdown(text: string, options: { inline?: boolean } = {}): string {
  ensureHooks();
  const escaped = text.replace(/</g, '&lt;'); // treat any HTML in agent text as literal text
  const html = options.inline ? (marked.parseInline(escaped) as string) : (marked.parse(escaped) as string);
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR, ALLOW_DATA_ATTR: false });
}
