/** Inline SVG icons (stroke = currentColor). Static strings only; never built from agent data. */
const svg = (body: string, extra = '') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"${extra}>${body}</svg>`;

export const ICONS = {
  sparkle: svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="M12 8.5l1.2 2.3 2.3 1.2-2.3 1.2L12 15.5l-1.2-2.3L8.5 12l2.3-1.2z" fill="currentColor"/>'),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  send: svg('<path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/>', ' stroke-width="2.2"'),
  attach: svg('<path d="M20.5 11.5l-8.3 8.3a5 5 0 01-7.1-7.1l8.6-8.6a3.4 3.4 0 014.8 4.8l-8.6 8.6a1.7 1.7 0 01-2.4-2.4l7.9-7.9"/>'),
  checkCircle: svg('<circle cx="12" cy="12" r="9"/><path d="M8.2 12.3l2.6 2.5 5-5.4"/>'),
  arrowRight: svg('<path d="M5 12h14M13 6l6 6-6 6"/>', ' stroke-width="2.2"'),
  thumbUp: svg('<path d="M7 11v9H4v-9zM7 11l4-8a2 2 0 012 2v4h5.5a2 2 0 012 2.3l-1.2 7A2 2 0 0117.3 20H7"/>'),
  thumbDown: svg('<path d="M7 13V4H4v9zM7 13l4 8a2 2 0 002-2v-4h5.5a2 2 0 002-2.3l-1.2-7A2 2 0 0017.3 4H7"/>'),
} as const;
