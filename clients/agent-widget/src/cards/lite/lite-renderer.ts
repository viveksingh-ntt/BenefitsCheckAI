import { compareVersions, type CardActionInvocation, type CardRenderContext, type CardRenderer, type RenderedCard } from '../renderer';

/**
 * Built-in, dependency-free Adaptive Cards renderer.
 *
 * Covers the schema subset the card catalogue uses (≤ 1.6): TextBlock, RichTextBlock, Image,
 * Container, ColumnSet/Column, FactSet, ActionSet, Badge, Input.Text/Number/Date/Time/Toggle/ChoiceSet,
 * Action.Submit/Execute/OpenUrl/ToggleVisibility/ShowCard, plus the custom `Org.SelectableList`.
 * Unknown elements use their `fallback` (or are dropped), as the Adaptive Cards spec requires.
 *
 * Styling is done with semantic `ac-*` classes and CSS custom properties defined by the widget theme,
 * so cards follow the portal's design tokens without a separate host config.
 */

type Json = Record<string, unknown>;

interface InputHandle {
  id: string;
  getValue(): string;
  validate(): boolean;
  focus(): void;
}

const SPACING = new Set(['none', 'small', 'default', 'medium', 'large', 'extraLarge', 'padding']);
const CONTAINER_STYLES = new Set(['default', 'emphasis', 'good', 'attention', 'warning', 'accent']);

const str = (value: unknown): string | undefined => (typeof value === 'string' ? value : undefined);
const arr = (value: unknown): Json[] => (Array.isArray(value) ? (value.filter((v) => v && typeof v === 'object') as Json[]) : []);
const lc = (value: unknown, fallback: string): string => (typeof value === 'string' ? value.charAt(0).toLowerCase() + value.slice(1) : fallback);

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export class LiteCardRenderer implements CardRenderer {
  readonly name = 'lite';
  readonly maxVersion = '1.6';

  render(card: Json, context: CardRenderContext): RenderedCard {
    return new RenderSession(context, this.maxVersion).renderRoot(card);
  }
}

class RenderSession {
  /**
   * Input scopes: one per (nested) card. An action submits the inputs of its own card and its
   * ancestors only, as the Adaptive Cards spec requires, so a required field inside a collapsed
   * Action.ShowCard never blocks the outer card's submit.
   */
  private scopes: InputHandle[][] = [[]];
  private disabled = false;
  private elementsById = new Map<string, HTMLElement>();
  private controls: Array<HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLElement> = [];
  private counter = 0;

  constructor(
    private readonly ctx: CardRenderContext,
    private readonly maxVersion: string,
  ) {}

  renderRoot(card: Json): RenderedCard {
    const root = el('div', 'ac-card');
    const version = str(card.version) ?? '1.0';
    if (card.type !== 'AdaptiveCard' || compareVersions(version, this.maxVersion) > 0) {
      const fallback = str(card.fallbackText) ?? 'This content can’t be displayed here.';
      const text = el('div', 'ac-text');
      text.innerHTML = this.ctx.markdown(fallback);
      root.append(text);
    } else {
      this.renderCardInto(card, root);
    }
    const controls = this.controls;
    const session = this;
    return {
      element: root,
      setDisabled(disabled: boolean) {
        session.disabled = disabled;
        root.classList.toggle('ac-disabled', disabled);
        for (const control of controls) {
          if ('disabled' in control) (control as HTMLInputElement).disabled = disabled;
          else control.setAttribute('aria-disabled', String(disabled));
        }
      },
    };
  }

  private renderCardInto(card: Json, target: HTMLElement): void {
    const body = el('div', 'ac-body');
    this.renderItems(arr(card.body), body);
    target.append(body);
    const actions = arr(card.actions);
    if (actions.length) target.append(this.renderActionRow(actions));
    if (card.selectAction && typeof card.selectAction === 'object') this.attachSelectAction(target, card.selectAction as Json);
  }

  private renderItems(items: Json[], container: HTMLElement): void {
    let first = true;
    for (const item of items) {
      const node = this.renderElement(item);
      if (!node) continue;
      this.applyCommon(item, node, first);
      container.append(node);
      first = false;
    }
  }

  private applyCommon(item: Json, node: HTMLElement, first: boolean): void {
    const spacing = lc(item.spacing, 'default');
    if (!first && SPACING.has(spacing)) node.classList.add(`ac-sp-${spacing}`);
    if (!first && item.separator === true) node.classList.add('ac-separator');
    if (item.isVisible === false) node.hidden = true;
    if (item.height === 'stretch') node.classList.add('ac-stretch');
    const id = str(item.id);
    if (id && !this.elementsById.has(id)) this.elementsById.set(id, node);
  }

  private renderElement(item: Json): HTMLElement | null {
    switch (item.type) {
      case 'TextBlock':
        return this.textBlock(item);
      case 'RichTextBlock':
        return this.richTextBlock(item);
      case 'Image':
        return this.image(item);
      case 'Container':
        return this.container(item);
      case 'ColumnSet':
        return this.columnSet(item);
      case 'FactSet':
        return this.factSet(item);
      case 'ActionSet':
        return this.renderActionRow(arr(item.actions));
      case 'Badge':
      case 'Org.Badge':
        return this.badge(item);
      case 'Input.Text':
      case 'Input.Number':
      case 'Input.Date':
      case 'Input.Time':
        return this.textInput(item);
      case 'Input.Toggle':
        return this.toggleInput(item);
      case 'Input.ChoiceSet':
        return this.choiceSet(item);
      case 'Org.SelectableList':
        return this.selectableList(item);
      default:
        return this.fallback(item);
    }
  }

  private fallback(item: Json): HTMLElement | null {
    const fb = item.fallback;
    if (fb && typeof fb === 'object') return this.renderElement(fb as Json);
    return null; // 'drop' or no fallback: unknown elements are dropped
  }

  // ---------------------------------------------------------------- display

  private textBlock(item: Json): HTMLElement {
    const node = el('div', 'ac-text');
    node.classList.add(`ac-size-${lc(item.size, 'default')}`, `ac-weight-${lc(item.weight, 'default')}`, `ac-color-${lc(item.color, 'default')}`);
    if (item.isSubtle === true) node.classList.add('ac-subtle');
    if (item.wrap !== true) node.classList.add('ac-nowrap');
    const align = lc(item.horizontalAlignment, '');
    if (align) node.classList.add(`ac-align-${align}`);
    if (typeof item.maxLines === 'number' && item.maxLines > 0) {
      node.classList.add('ac-clamp');
      node.style.setProperty('--ac-lines', String(item.maxLines));
    }
    if (item.style === 'heading') {
      node.setAttribute('role', 'heading');
      node.setAttribute('aria-level', '3');
    }
    node.innerHTML = this.ctx.markdown(str(item.text) ?? '');
    return node;
  }

  private richTextBlock(item: Json): HTMLElement {
    const node = el('div', 'ac-text ac-rich');
    for (const inline of Array.isArray(item.inlines) ? item.inlines : []) {
      if (typeof inline === 'string') {
        node.append(document.createTextNode(inline));
        continue;
      }
      const run = inline as Json;
      if (run.type !== 'TextRun') continue;
      const span = el('span', `ac-size-${lc(run.size, 'default')} ac-weight-${lc(run.weight, 'default')} ac-color-${lc(run.color, 'default')}`, str(run.text) ?? '');
      if (run.isSubtle) span.classList.add('ac-subtle');
      if (run.italic) span.style.fontStyle = 'italic';
      if (run.strikethrough) span.style.textDecoration = 'line-through';
      if (run.underline) span.style.textDecoration = 'underline';
      if (run.highlight) span.classList.add('ac-highlight');
      node.append(span);
    }
    return node;
  }

  private image(item: Json): HTMLElement | null {
    const url = str(item.url);
    if (!url || !/^https:\/\//i.test(url)) return null; // no data:, http: or javascript: images from agents
    const wrap = el('div', 'ac-image');
    const align = lc(item.horizontalAlignment, '');
    if (align) wrap.classList.add(`ac-align-${align}`);
    const img = el('img');
    img.src = url;
    img.alt = str(item.altText) ?? '';
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    img.classList.add(`ac-img-${lc(item.size, 'auto')}`);
    if (item.style === 'person') img.classList.add('ac-person');
    const width = str(item.width);
    if (width && /^\d+px$/.test(width)) img.style.width = width;
    wrap.append(img);
    if (item.selectAction && typeof item.selectAction === 'object') this.attachSelectAction(wrap, item.selectAction as Json);
    return wrap;
  }

  private container(item: Json): HTMLElement {
    const node = el('div', 'ac-container');
    const style = lc(item.style, '');
    if (CONTAINER_STYLES.has(style) && style !== 'default') node.classList.add('ac-styled', `ac-style-${style}`);
    const vAlign = lc(item.verticalContentAlignment, '');
    if (vAlign) node.classList.add(`ac-valign-${vAlign}`);
    this.renderItems(arr(item.items), node);
    if (item.selectAction && typeof item.selectAction === 'object') this.attachSelectAction(node, item.selectAction as Json);
    return node;
  }

  private columnSet(item: Json): HTMLElement {
    const node = el('div', 'ac-columns');
    const style = lc(item.style, '');
    if (CONTAINER_STYLES.has(style) && style !== 'default') node.classList.add('ac-styled', `ac-style-${style}`);
    let first = true;
    for (const column of arr(item.columns)) {
      const col = el('div', 'ac-column');
      const width = column.width;
      if (width === 'auto') col.style.flex = '0 0 auto';
      else if (typeof width === 'number') col.style.flex = `${width} ${width} 0`;
      else if (typeof width === 'string' && /^\d+px$/.test(width)) col.style.flex = `0 0 ${width}`;
      else if (typeof width === 'string' && /^\d+(\.\d+)?$/.test(width)) col.style.flex = `${width} ${width} 0`;
      else col.style.flex = '1 1 0';
      const colStyle = lc(column.style, '');
      if (CONTAINER_STYLES.has(colStyle) && colStyle !== 'default') col.classList.add('ac-styled', `ac-style-${colStyle}`);
      const vAlign = lc(column.verticalContentAlignment, '');
      if (vAlign) col.classList.add(`ac-valign-${vAlign}`);
      this.renderItems(arr(column.items), col);
      if (!first && column.separator === true) col.classList.add('ac-col-separator');
      if (column.isVisible === false) col.hidden = true;
      const id = str(column.id);
      if (id) this.elementsById.set(id, col);
      if (column.selectAction && typeof column.selectAction === 'object') this.attachSelectAction(col, column.selectAction as Json);
      node.append(col);
      first = false;
    }
    if (item.selectAction && typeof item.selectAction === 'object') this.attachSelectAction(node, item.selectAction as Json);
    return node;
  }

  private factSet(item: Json): HTMLElement {
    const node = el('dl', 'ac-facts');
    for (const fact of arr(item.facts)) {
      const dt = el('dt', 'ac-fact-title', str(fact.title) ?? '');
      const dd = el('dd', 'ac-fact-value');
      dd.innerHTML = this.ctx.markdown(str(fact.value) ?? '');
      node.append(dt, dd);
    }
    return node;
  }

  private badge(item: Json): HTMLElement {
    const node = el('span', `ac-badge ac-badge-${lc(item.style, 'default')}`);
    const wrap = el('div', 'ac-badge-row');
    const align = lc(item.horizontalAlignment, '');
    if (align) wrap.classList.add(`ac-align-${align}`);
    if (item.icon) node.classList.add('ac-badge-icon');
    node.textContent = str(item.text) ?? '';
    wrap.append(node);
    return wrap;
  }

  // ----------------------------------------------------------------- inputs

  private nextId(base?: string): string {
    this.counter += 1;
    return `${this.ctx.idPrefix}-${(base ?? 'in').replace(/[^A-Za-z0-9_-]/g, '')}-${this.counter}`;
  }

  private labelled(item: Json, control: HTMLElement, controlId: string): { wrap: HTMLElement; error: HTMLElement } {
    const wrap = el('div', 'ac-input');
    const label = str(item.label);
    if (label) {
      const lab = el('label', 'ac-label', label);
      lab.htmlFor = controlId;
      wrap.append(lab);
    } else if (str(item.placeholder)) {
      control.setAttribute('aria-label', str(item.placeholder)!);
    }
    wrap.append(control);
    const error = el('div', 'ac-error');
    error.id = `${controlId}-err`;
    error.hidden = true;
    wrap.append(error);
    return { wrap, error };
  }

  private registerInput(
    item: Json,
    getValue: () => string,
    focusTarget: HTMLElement,
    error: HTMLElement,
    extraCheck?: (value: string) => boolean,
  ): void {
    const id = str(item.id);
    if (!id) return;
    const required = item.isRequired === true;
    if (required) focusTarget.setAttribute('aria-required', 'true');
    const regex = str(item.regex);
    const validate = (): boolean => {
      const value = getValue();
      let ok = !(required && value.trim() === '');
      if (ok && regex && value) {
        try {
          ok = new RegExp(`^(?:${regex})$`).test(value);
        } catch {
          ok = true;
        }
      }
      if (ok && extraCheck) ok = extraCheck(value);
      error.hidden = ok;
      error.textContent = ok ? '' : (str(item.errorMessage) ?? this.ctx.strings.required);
      if (ok) {
        focusTarget.removeAttribute('aria-invalid');
        focusTarget.removeAttribute('aria-describedby');
      } else {
        focusTarget.setAttribute('aria-invalid', 'true');
        focusTarget.setAttribute('aria-describedby', error.id);
      }
      return ok;
    };
    this.scopes[this.scopes.length - 1].push({ id, getValue, validate, focus: () => focusTarget.focus() });
  }

  private textInput(item: Json): HTMLElement {
    const controlId = this.nextId(str(item.id));
    const multiline = item.type === 'Input.Text' && item.isMultiline === true;
    const control = multiline ? el('textarea', 'ac-field') : el('input', 'ac-field');
    control.id = controlId;
    if (control instanceof HTMLInputElement) {
      const typeMap: Record<string, string> = { 'Input.Number': 'number', 'Input.Date': 'date', 'Input.Time': 'time' };
      const styleMap: Record<string, string> = { tel: 'tel', email: 'email', url: 'url', password: 'password' };
      control.type = typeMap[item.type as string] ?? styleMap[lc(item.style, 'text')] ?? 'text';
      if (item.type === 'Input.Number') {
        if (typeof item.min === 'number') control.min = String(item.min);
        if (typeof item.max === 'number') control.max = String(item.max);
        control.inputMode = 'decimal';
      }
      if (item.type === 'Input.Date' || item.type === 'Input.Time') {
        if (str(item.min)) control.min = str(item.min)!;
        if (str(item.max)) control.max = str(item.max)!;
      }
    } else {
      control.rows = 3;
    }
    if (str(item.placeholder)) control.placeholder = str(item.placeholder)!;
    if (typeof item.maxLength === 'number' && item.maxLength > 0) control.maxLength = item.maxLength;
    if (item.value !== undefined && item.value !== null) control.value = String(item.value);
    const { wrap, error } = this.labelled(item, control, controlId);
    this.registerInput(item, () => control.value, control, error, (value) => {
      if (item.type !== 'Input.Number' || value === '') return true;
      const n = Number(value);
      if (!Number.isFinite(n)) return false;
      if (typeof item.min === 'number' && n < item.min) return false;
      if (typeof item.max === 'number' && n > item.max) return false;
      return true;
    });
    this.controls.push(control);
    return wrap;
  }

  private toggleInput(item: Json): HTMLElement {
    const controlId = this.nextId(str(item.id));
    const wrap = el('div', 'ac-input ac-toggle');
    const label = el('label', 'ac-check');
    const box = el('input');
    box.type = 'checkbox';
    box.id = controlId;
    const valueOn = str(item.valueOn) ?? 'true';
    const valueOff = str(item.valueOff) ?? 'false';
    box.checked = item.value === valueOn;
    label.append(box, el('span', '', str(item.title) ?? str(item.label) ?? ''));
    if (str(item.label) && str(item.title)) wrap.append(el('div', 'ac-label', str(item.label)));
    wrap.append(label);
    const error = el('div', 'ac-error');
    error.id = `${controlId}-err`;
    error.hidden = true;
    wrap.append(error);
    // A required toggle must be switched on (Adaptive Cards 1.3 semantics).
    this.registerInput(item, () => (box.checked ? valueOn : valueOff), box, error, () => item.isRequired !== true || box.checked);
    this.controls.push(box);
    return wrap;
  }

  private choiceSet(item: Json): HTMLElement {
    const choices = arr(item.choices).map((c) => ({ title: str(c.title) ?? String(c.value ?? ''), value: String(c.value ?? '') }));
    const multi = item.isMultiSelect === true;
    const rawStyle = lc(item.style, 'compact');
    const style = rawStyle === 'filtered' ? 'compact' : rawStyle; // filtered (typeahead) renders as a dropdown
    const initial = new Set((str(item.value) ?? '').split(',').filter(Boolean));

    if (style === 'compact' && !multi) {
      const controlId = this.nextId(str(item.id));
      const select = el('select', 'ac-field ac-select');
      select.id = controlId;
      if (str(item.placeholder) || !initial.size) {
        const ph = el('option', '', str(item.placeholder) ?? '');
        ph.value = '';
        ph.disabled = item.isRequired === true;
        select.append(ph);
      }
      for (const choice of choices) {
        const option = el('option', '', choice.title);
        option.value = choice.value;
        option.selected = initial.has(choice.value);
        select.append(option);
      }
      const { wrap, error } = this.labelled(item, select, controlId);
      this.registerInput(item, () => select.value, select, error);
      this.controls.push(select);
      return wrap;
    }

    // expanded (or multi-select): radios / checkboxes in a fieldset
    const fieldset = el('fieldset', 'ac-input ac-choices');
    const legendText = str(item.label);
    if (legendText) fieldset.append(el('legend', 'ac-label', legendText));
    const name = this.nextId(str(item.id));
    const boxes: HTMLInputElement[] = [];
    for (const choice of choices) {
      const label = el('label', 'ac-check');
      const box = el('input');
      box.type = multi ? 'checkbox' : 'radio';
      box.name = name;
      box.value = choice.value;
      box.checked = initial.has(choice.value);
      label.append(box, el('span', '', choice.title));
      fieldset.append(label);
      boxes.push(box);
      this.controls.push(box);
    }
    const error = el('div', 'ac-error');
    error.id = `${name}-err`;
    error.hidden = true;
    fieldset.append(error);
    this.registerInput(item, () => boxes.filter((b) => b.checked).map((b) => b.value).join(','), boxes[0] ?? fieldset, error);
    return fieldset;
  }

  /**
   * Org.SelectableList: rich, radio-selectable rows (doctors, services).
   * Native radios inside labels give keyboard support (arrow keys) and screen-reader semantics for free.
   */
  private selectableList(item: Json): HTMLElement {
    const fieldset = el('fieldset', 'ac-input ac-selectable');
    const legend = el('legend', str(item.label) ? 'ac-label' : 'ac-sr-only', str(item.label) ?? str(item.ariaLabel) ?? 'Options');
    fieldset.append(legend);
    const name = this.nextId(str(item.id));
    const radios: HTMLInputElement[] = [];
    const rows: HTMLElement[] = [];
    const selected = str(item.value);

    const sync = () => radios.forEach((radio, i) => rows[i].classList.toggle('is-selected', radio.checked));

    for (const option of arr(item.items)) {
      const value = String(option.value ?? option.id ?? '');
      const row = el('label', 'ac-option');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = name;
      radio.value = value;
      radio.checked = selected !== undefined && selected === value;
      radio.addEventListener('change', sync);

      const content = el('div', 'ac-option-body');
      const head = el('div', 'ac-option-head');
      const avatar = str(option.initials);
      if (avatar) head.append(el('span', 'ac-avatar', avatar));
      const titles = el('div', 'ac-option-titles');
      titles.append(el('div', 'ac-option-title', str(option.title) ?? value));
      if (str(option.subtitle)) titles.append(el('div', 'ac-option-subtitle', str(option.subtitle)));
      head.append(titles);
      content.append(head);
      if (str(option.description)) content.append(el('div', 'ac-option-desc', str(option.description)));
      if (str(option.highlight)) content.append(el('div', `ac-option-highlight ac-color-${lc(option.highlightStyle, 'good')}`, str(option.highlight)));
      if (str(option.meta)) content.append(el('div', 'ac-option-meta', str(option.meta)));

      row.append(radio, content);
      fieldset.append(row);
      radios.push(radio);
      rows.push(row);
      this.controls.push(radio);
    }
    sync();
    const error = el('div', 'ac-error');
    error.id = `${name}-err`;
    error.hidden = true;
    fieldset.append(error);
    this.registerInput(item, () => radios.find((r) => r.checked)?.value ?? '', radios[0] ?? fieldset, error);
    return fieldset;
  }

  // ---------------------------------------------------------------- actions

  private renderActionRow(actions: Json[]): HTMLElement {
    const scopes = [...this.scopes]; // this card and its ancestors, captured for these actions
    const row = el('div', 'ac-actions');
    const showCardHost = el('div', 'ac-showcard-host');
    for (const action of actions) {
      const button = el('button', 'ac-btn');
      button.type = 'button';
      button.textContent = str(action.title) ?? '';
      const style = lc(action.style, 'default');
      button.classList.add(`ac-btn-${style}`);
      if (str(action.tooltip)) button.title = str(action.tooltip)!;
      if (action.isEnabled === false) button.disabled = true;

      if (action.type === 'Action.ShowCard' && action.card && typeof action.card === 'object') {
        const panel = el('div', 'ac-showcard');
        panel.hidden = true;
        panel.id = this.nextId('showcard');
        this.scopes.push([]);
        this.renderCardInto(action.card as Json, panel);
        this.scopes.pop();
        showCardHost.append(panel);
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', panel.id);
        button.addEventListener('click', () => {
          const open = panel.hidden;
          for (const other of showCardHost.children) (other as HTMLElement).hidden = true;
          row.querySelectorAll('[aria-expanded]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
          panel.hidden = !open;
          button.setAttribute('aria-expanded', String(open));
        });
      } else {
        button.addEventListener('click', () => this.invoke(action, scopes));
      }
      this.controls.push(button);
      row.append(button);
    }
    if (!showCardHost.childElementCount) return row;
    const wrap = el('div', 'ac-actions-wrap');
    wrap.append(row, showCardHost);
    return wrap;
  }

  private attachSelectAction(node: HTMLElement, action: Json): void {
    if (action.type === 'Action.ShowCard') return; // not allowed as selectAction
    const scopes = [...this.scopes];
    node.classList.add('ac-selectable-region');
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    if (str(action.title)) node.setAttribute('aria-label', str(action.title)!);
    node.addEventListener('click', (event) => {
      if (this.disabled || (event.target as HTMLElement).closest('button, input, select, textarea, a, label')) return;
      this.invoke(action, scopes);
    });
    node.addEventListener('keydown', (event) => {
      if (event.target !== node || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      if (!this.disabled) this.invoke(action, scopes);
    });
    this.controls.push(node);
  }

  private invoke(action: Json, scopes: InputHandle[][]): void {
    if (this.disabled) return;
    const type = action.type;
    if (type === 'Action.ToggleVisibility') {
      for (const target of Array.isArray(action.targetElements) ? action.targetElements : []) {
        const id = typeof target === 'string' ? target : str((target as Json).elementId);
        const node = id ? this.elementsById.get(id) : undefined;
        if (!node) continue;
        const explicit = typeof target === 'object' ? (target as Json).isVisible : undefined;
        node.hidden = typeof explicit === 'boolean' ? !explicit : !node.hidden;
      }
      return;
    }
    if (type === 'Action.OpenUrl') {
      const url = str(action.url);
      if (url) this.ctx.onAction({ type: 'Action.OpenUrl', url, title: str(action.title), data: {}, actionData: {} });
      return;
    }
    if (type !== 'Action.Submit' && type !== 'Action.Execute') return;

    const rawData = action.data;
    const actionData: Record<string, unknown> =
      rawData && typeof rawData === 'object' && !Array.isArray(rawData) ? { ...(rawData as Json) } : rawData !== undefined ? { value: rawData } : {};

    const associated = lc(action.associatedInputs, 'auto');
    const values: Record<string, string> = {};
    if (associated !== 'none') {
      const inputs = scopes.flat();
      const invalid = inputs.filter((input) => !input.validate());
      if (invalid.length) {
        invalid[0].focus();
        return;
      }
      for (const input of inputs) values[input.id] = input.getValue();
    }

    const invocation: CardActionInvocation = {
      type,
      title: str(action.title),
      verb: str(action.verb),
      data: { ...actionData, ...values },
      actionData,
    };
    this.ctx.onAction(invocation);
  }
}
