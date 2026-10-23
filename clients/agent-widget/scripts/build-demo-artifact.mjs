// Produces a single self-contained demo page (bundles inlined) for publishing: artifact/care-assistant-playground.html
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const html = readFileSync('demo/index.html', 'utf8');
const between = (start, end) => {
  const a = html.indexOf(start);
  const b = html.indexOf(end);
  if (a < 0 || b < 0) throw new Error(`markers ${start}/${end} not found`);
  return html.slice(a + start.length, b);
};

const inline = (src) => {
  const code = readFileSync(src.replace('../', ''), 'utf8')
    .replace(/\/\/# sourceMappingURL=.*$/m, '')
    .replace(/<\/script/gi, '<\\/script');
  return `<script>${code}</script>`;
};

const head = between('<!-- BEGIN-HEAD -->', '<!-- END-HEAD -->');
const body = between('<!-- BEGIN-BODY -->', '<!-- END-BODY -->').replace(/<script src="([^"]+)"><\/script>/g, (_m, src) => inline(src));

mkdirSync('artifact', { recursive: true });
writeFileSync('artifact/care-assistant-playground.html', `${head.trim()}\n${body.trim()}\n`);
console.log('wrote artifact/care-assistant-playground.html');
