/** Shadow-DOM styles: widget chrome + Adaptive Card (ac-*) styles. All colours come from theme tokens. */
export const WIDGET_CSS = /* css */ `
:host {
  all: initial;
  display: contents;
  font-family: var(--aw-font);
  color: var(--aw-text);
  font-size: 14px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}
:host([mode='inline']), :host([mode='fullpage']) { display: block; height: 100%; }
*, *::before, *::after { box-sizing: border-box; }
button, input, select, textarea { font: inherit; color: inherit; }
[hidden] { display: none !important; }
.sr-only, .ac-sr-only {
  position: absolute !important; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
:focus-visible { outline: 2px solid var(--aw-brand); outline-offset: 2px; }

/* ---------------------------------------------------------------- frame */
.aw-launcher {
  position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
  width: 56px; height: 56px; border-radius: 50%; border: 0; cursor: pointer;
  background: var(--aw-brand); color: var(--aw-brand-contrast);
  display: grid; place-items: center;
  box-shadow: 0 6px 20px rgba(16, 40, 32, .25);
  transition: transform .15s ease, background .15s ease;
}
.aw-launcher:hover { background: var(--aw-brand-strong); transform: translateY(-1px); }
.aw-launcher svg { width: 26px; height: 26px; }
.pos-bottom-left .aw-launcher { right: auto; left: 20px; }

.aw-panel {
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--aw-surface-alt);
  border: 1px solid var(--aw-border);
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(16, 40, 32, .18);
}
.mode-launcher .aw-panel {
  position: fixed; right: 20px; bottom: 88px; z-index: 2147483000;
  width: min(400px, calc(100vw - 32px)); height: min(760px, calc(100vh - 112px));
}
.mode-launcher.pos-bottom-left .aw-panel { right: auto; left: 20px; }
.mode-docked .aw-panel {
  position: fixed; top: 0; right: 0; bottom: 0; z-index: 2147483000;
  width: min(400px, 100vw); border-radius: 0; border-width: 0 0 0 1px;
}
.aw-frame.mode-inline, .aw-frame.mode-fullpage { height: 100%; }
.mode-inline .aw-panel, .mode-fullpage .aw-panel { width: 100%; height: 100%; box-shadow: none; }
.mode-fullpage .aw-panel { height: 100vh; border-radius: 0; }
@media (max-width: 480px) {
  .mode-launcher .aw-panel, .mode-docked .aw-panel {
    inset: 0; width: 100vw; height: 100dvh; border-radius: 0; border: 0;
  }
}

/* ---------------------------------------------------------------- header */
.aw-header {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 14px 12px 16px; background: var(--aw-surface);
}
.aw-mark {
  flex: none; width: 36px; height: 36px; border-radius: 9px;
  display: grid; place-items: center; background: var(--aw-brand-soft); color: var(--aw-brand);
}
.aw-mark svg { width: 20px; height: 20px; }
.aw-titles { flex: 1; min-width: 0; }
.aw-title { margin: 0; font-size: 16.5px; font-weight: 650; letter-spacing: -.01em; line-height: 1.25; }
.aw-tagline { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--aw-text-muted); }
.aw-tagline::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--aw-good); }
.aw-icon-btn {
  flex: none; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent;
  display: grid; place-items: center; color: var(--aw-text-muted); cursor: pointer;
}
.aw-icon-btn:hover { background: var(--aw-surface-sunken); color: var(--aw-text); }
.aw-icon-btn svg { width: 18px; height: 18px; }

.aw-crumb {
  display: flex; justify-content: space-between; gap: 8px;
  padding: 6px 16px; font-size: 11.5px; color: var(--aw-text-muted);
  background: var(--aw-surface-sunken); border-block: 1px solid var(--aw-border);
}
.aw-crumb-env { white-space: nowrap; }

.aw-context {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; background: var(--aw-surface); border-bottom: 1px solid var(--aw-border);
}
.aw-avatar {
  flex: none; width: 30px; height: 30px; border-radius: 50%;
  display: grid; place-items: center; font-size: 11px; font-weight: 600;
  background: var(--aw-surface-sunken); color: var(--aw-text-muted); letter-spacing: .02em;
}
.aw-context-name { font-size: 13px; font-weight: 600; line-height: 1.3; }
.aw-context-meta { font-size: 11.5px; color: var(--aw-text-muted); }

/* ---------------------------------------------------------------- log */
.aw-log {
  flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
  padding: 12px 14px 16px; display: flex; flex-direction: column; gap: 10px;
}
.aw-day { align-self: center; font-size: 11.5px; color: var(--aw-text-muted); margin: 2px 0; }
.aw-user { align-self: flex-end; max-width: 82%; display: flex; flex-direction: column; align-items: flex-end; gap: 3px; }
.aw-bubble {
  background: var(--aw-brand-soft); border-radius: 14px 14px 4px 14px;
  padding: 9px 12px; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere;
}
.aw-user-status { font-size: 11px; color: var(--aw-text-muted); }
.aw-user-status.is-failed { color: var(--aw-attention); }
.aw-user-status button { border: 0; background: none; padding: 0; color: var(--aw-brand); font-weight: 600; cursor: pointer; text-decoration: underline; }

.aw-bot { display: flex; flex-direction: column; gap: 6px; max-width: 100%; }
.aw-bot-text { font-size: 14px; overflow-wrap: anywhere; }
.aw-bot-text p { margin: 0 0 6px; } .aw-bot-text p:last-child { margin-bottom: 0; }
.aw-bot-text ul, .aw-bot-text ol { margin: 4px 0; padding-left: 20px; }
.aw-bot-text a, .ac-text a { color: var(--aw-brand); }
.aw-bot-text.is-streaming::after {
  content: ''; display: inline-block; width: 7px; height: 14px; margin-left: 2px; vertical-align: -2px;
  background: var(--aw-brand); animation: aw-blink 1s steps(2) infinite;
}
@keyframes aw-blink { 50% { opacity: 0; } }
.aw-chip-result {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--aw-good); font-weight: 500;
}
.aw-chip-result svg { width: 14px; height: 14px; flex: none; }
.aw-chip-result.is-warning { color: var(--aw-warning); }
.aw-feedback { display: flex; gap: 2px; }
.aw-feedback .aw-icon-btn { width: 26px; height: 26px; }
.aw-feedback .aw-icon-btn svg { width: 14px; height: 14px; }
.aw-feedback .aw-icon-btn[aria-pressed='true'] { color: var(--aw-brand); background: var(--aw-brand-soft); }

.aw-progress { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--aw-text-muted); }
.aw-dots { display: inline-flex; gap: 3px; }
.aw-dots span { width: 6px; height: 6px; border-radius: 50%; background: var(--aw-text-muted); animation: aw-dot 1.2s infinite ease-in-out; }
.aw-dots span:nth-child(2) { animation-delay: .15s; } .aw-dots span:nth-child(3) { animation-delay: .3s; }
@keyframes aw-dot { 0%, 80%, 100% { opacity: .25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }
@media (prefers-reduced-motion: reduce) {
  .aw-dots span, .aw-bot-text.is-streaming::after { animation: none; }
}

.aw-banner {
  margin: 0 14px; padding: 8px 12px; border-radius: 8px; font-size: 12.5px;
  background: #fff4e0; color: var(--aw-warning); display: flex; justify-content: space-between; gap: 8px;
}
.aw-banner.is-error { background: #fdecea; color: var(--aw-attention); }
.aw-banner button { border: 0; background: none; font-weight: 600; color: inherit; cursor: pointer; text-decoration: underline; }

/* ---------------------------------------------------------------- suggestions */
.aw-suggestions { padding: 10px 14px 4px; border-top: 1px solid var(--aw-border); background: var(--aw-surface-alt); }
.aw-suggestions-label { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; margin-bottom: 7px; }
.aw-suggestions-label svg { width: 14px; height: 14px; color: var(--aw-brand); }
.aw-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.aw-chip {
  border: 1px solid var(--aw-border-strong); background: var(--aw-surface); border-radius: 999px;
  padding: 4px 11px; font-size: 12px; font-weight: 500; cursor: pointer; color: var(--aw-text);
}
.aw-chip:hover { border-color: var(--aw-brand); }
.aw-chip.is-recommended { background: var(--aw-brand-soft); border-color: var(--aw-brand); color: var(--aw-brand-strong); }

/* ---------------------------------------------------------------- composer */
.aw-composer { padding: 10px 14px 6px; background: var(--aw-surface-alt); }
.aw-input-row {
  display: flex; align-items: flex-end; gap: 6px; padding: 6px 6px 6px 8px;
  background: var(--aw-surface); border: 1px solid var(--aw-border-strong); border-radius: 12px;
}
.aw-input-row:focus-within { border-color: var(--aw-brand); box-shadow: 0 0 0 3px var(--aw-brand-soft); }
.aw-input {
  flex: 1; min-width: 0; border: 0; outline: none; resize: none; background: transparent;
  font-size: 14px; line-height: 20px; padding: 5px 2px; max-height: 120px;
}
.aw-input::placeholder { color: var(--aw-text-muted); }
.aw-send {
  flex: none; width: 32px; height: 32px; border: 0; border-radius: 8px; cursor: pointer;
  background: var(--aw-brand); color: var(--aw-brand-contrast); display: grid; place-items: center;
}
.aw-send:disabled { opacity: .45; cursor: default; }
.aw-send svg { width: 18px; height: 18px; }
.aw-files { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.aw-file { font-size: 11.5px; background: var(--aw-surface-sunken); border-radius: 6px; padding: 3px 8px; display: inline-flex; gap: 6px; align-items: center; }
.aw-file button { border: 0; background: none; cursor: pointer; padding: 0; color: var(--aw-text-muted); }
.aw-footer {
  display: flex; justify-content: space-between; gap: 8px; align-items: center;
  padding: 2px 16px 10px; font-size: 10.5px; color: var(--aw-text-muted); background: var(--aw-surface-alt);
}
.aw-support { border: 0; background: none; padding: 0; cursor: pointer; font-size: 11px; font-weight: 600; color: var(--aw-brand); }

/* ================================================================ Adaptive Cards */
.aw-card {
  background: var(--aw-surface); border: 1px solid var(--aw-border); border-radius: 12px;
  padding: 14px; box-shadow: 0 1px 2px rgba(16, 40, 32, .04);
}
.aw-card.is-stale { opacity: .78; }
.aw-card-status { margin-top: 10px; font-size: 11.5px; color: var(--aw-text-muted); display: flex; align-items: center; gap: 6px; }
.aw-card-status svg { width: 13px; height: 13px; color: var(--aw-good); }

.ac-card { font-size: 13.5px; }
.ac-body > * { margin: 0; }
.ac-sp-none { margin-top: 0 !important; } .ac-sp-small { margin-top: 4px !important; }
.ac-sp-default { margin-top: 8px !important; } .ac-sp-medium { margin-top: 14px !important; }
.ac-sp-large { margin-top: 22px !important; } .ac-sp-extraLarge { margin-top: 30px !important; }
.ac-sp-padding { margin-top: 14px !important; }
.ac-separator { border-top: 1px solid var(--aw-border); padding-top: 8px; }

.ac-text { overflow-wrap: anywhere; }
.ac-text p { margin: 0; } .ac-text p + p { margin-top: 4px; }
.ac-text ul, .ac-text ol { margin: 2px 0; padding-left: 18px; }
.ac-nowrap { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ac-clamp { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: var(--ac-lines); overflow: hidden; }
.ac-size-small { font-size: 12px; } .ac-size-default { font-size: 13.5px; }
.ac-size-medium { font-size: 15.5px; line-height: 1.3; } .ac-size-large { font-size: 19px; line-height: 1.25; }
.ac-size-extraLarge { font-size: 23px; line-height: 1.2; }
.ac-weight-lighter { font-weight: 300; } .ac-weight-bolder { font-weight: 650; }
.ac-color-good { color: var(--aw-good); } .ac-color-warning { color: var(--aw-warning); }
.ac-color-attention { color: var(--aw-attention); } .ac-color-accent { color: var(--aw-brand); }
.ac-color-light { color: var(--aw-surface); }
.ac-subtle { color: var(--aw-text-muted); }
.ac-highlight { background: #fff3bf; }
.ac-align-center { text-align: center; justify-content: center; } .ac-align-right { text-align: right; justify-content: flex-end; }

.ac-container { display: flex; flex-direction: column; }
.ac-styled { border-radius: 8px; padding: 10px 12px; }
.ac-style-emphasis { background: var(--aw-surface-sunken); }
.ac-style-good, .ac-style-accent { background: var(--aw-brand-soft); }
.ac-style-attention { background: #fdecea; } .ac-style-warning { background: #fff4e0; }
.ac-valign-center { justify-content: center; } .ac-valign-bottom { justify-content: flex-end; }
.ac-columns { display: flex; gap: 10px; }
.ac-column { min-width: 0; display: flex; flex-direction: column; }
.ac-col-separator { border-left: 1px solid var(--aw-border); padding-left: 10px; }
.ac-selectable-region { cursor: pointer; border-radius: 8px; }
.ac-selectable-region:hover { background: var(--aw-surface-sunken); }

.ac-image img { display: block; max-width: 100%; height: auto; border-radius: 6px; }
.ac-img-small { width: 40px; } .ac-img-medium { width: 80px; } .ac-img-large { width: 160px; }
.ac-img-stretch { width: 100%; }
.ac-person { border-radius: 50% !important; aspect-ratio: 1; object-fit: cover; }

.ac-facts { display: grid; grid-template-columns: minmax(80px, 34%) 1fr; gap: 7px 12px; margin: 0; font-size: 13px; }
.ac-fact-title { color: var(--aw-text-muted); }
.ac-fact-value { margin: 0; font-weight: 550; }
.ac-fact-value p { margin: 0; }

.ac-badge-row { display: flex; }
.ac-badge {
  display: inline-flex; align-items: center; gap: 4px; border-radius: 6px; padding: 3px 9px;
  font-size: 12px; font-weight: 600; background: var(--aw-surface-sunken); color: var(--aw-text);
}
.ac-badge-good, .ac-badge-accent { background: var(--aw-brand-soft); color: var(--aw-good); }
.ac-badge-warning { background: #fff4e0; color: var(--aw-warning); }
.ac-badge-attention { background: #fdecea; color: var(--aw-attention); }

/* inputs */
.ac-input { display: flex; flex-direction: column; gap: 5px; border: 0; padding: 0; margin: 0; min-width: 0; }
.ac-label { font-size: 12.5px; font-weight: 600; padding: 0; }
.ac-field {
  width: 100%; min-height: 38px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--aw-border-strong); background: var(--aw-surface); font-size: 13.5px;
}
textarea.ac-field { resize: vertical; min-height: 64px; }
.ac-field:focus { outline: none; border-color: var(--aw-brand); box-shadow: 0 0 0 3px var(--aw-brand-soft); }
.ac-field[aria-invalid='true'] { border-color: var(--aw-attention); }
.ac-select {
  appearance: none; padding-right: 30px; cursor: pointer;
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 15px) 50%, calc(100% - 10px) 50%; background-size: 5px 5px; background-repeat: no-repeat;
}
.ac-error { font-size: 12px; color: var(--aw-attention); }
.ac-check { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; }
.ac-check input { margin: 2px 0 0; accent-color: var(--aw-brand); width: 16px; height: 16px; flex: none; }
.ac-choices { gap: 7px; }

/* Org.SelectableList */
.ac-selectable { gap: 8px; }
.ac-option {
  display: flex; gap: 10px; align-items: flex-start; cursor: pointer;
  border: 1px solid var(--aw-border); border-radius: 10px; padding: 11px 12px;
  background: var(--aw-surface); transition: border-color .12s ease, background .12s ease;
}
.ac-option:hover { border-color: var(--aw-border-strong); }
.ac-option.is-selected { border-color: var(--aw-brand); background: var(--aw-brand-soft); box-shadow: inset 0 0 0 .5px var(--aw-brand); }
.ac-option input { margin: 3px 0 0; accent-color: var(--aw-brand); width: 15px; height: 15px; flex: none; }
.ac-option:has(input:focus-visible) { outline: 2px solid var(--aw-brand); outline-offset: 2px; }
.ac-option-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.ac-option-head { display: flex; align-items: center; gap: 9px; margin-bottom: 2px; }
.ac-avatar {
  flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
  background: var(--aw-surface-sunken); color: var(--aw-text-muted); font-size: 10.5px; font-weight: 650;
}
.ac-option.is-selected .ac-avatar { background: var(--aw-surface); }
.ac-option-title { font-size: 13.5px; font-weight: 650; line-height: 1.3; }
.ac-option-subtitle, .ac-option-meta { font-size: 12px; color: var(--aw-text-muted); }
.ac-option-desc { font-size: 12.5px; }
.ac-option-highlight { font-size: 12px; font-weight: 600; }

/* actions */
.ac-actions { display: flex; gap: 8px; margin-top: 14px; }
.ac-actions-wrap .ac-actions { margin-top: 14px; }
.ac-body > .ac-actions { margin-top: 10px; }
.ac-btn {
  flex: 1 1 0; min-width: 0; min-height: 38px; padding: 8px 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--aw-border-strong); background: var(--aw-surface); color: var(--aw-text);
  font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ac-btn:hover { border-color: var(--aw-text-muted); }
.ac-btn-positive { background: var(--aw-brand); border-color: var(--aw-brand); color: var(--aw-brand-contrast); }
.ac-btn-positive:hover { background: var(--aw-brand-strong); border-color: var(--aw-brand-strong); }
.ac-btn-destructive { color: var(--aw-attention); border-color: var(--aw-attention); }
.ac-btn:disabled { opacity: .5; cursor: default; }
.ac-btn[aria-expanded='true'] { border-color: var(--aw-brand); }
.ac-showcard { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--aw-border); }
.ac-disabled .ac-option, .ac-disabled .ac-field { cursor: default; }
`;
