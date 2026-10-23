/**
 * Adapter for Microsoft's official Adaptive Cards JavaScript SDK (`adaptivecards` v3.x).
 *
 * Usage (portal bundle):
 *   import * as AdaptiveCards from 'adaptivecards';
 *   import { createSdkRenderer } from '@yourorg/agent-widget/sdk-renderer';
 *   widget.init({ ..., cardRenderer: createSdkRenderer(AdaptiveCards) });
 *
 * The SDK module is passed in rather than imported, so the widget bundle stays free of it and
 * portals choose the SDK version.
 *
 * STATUS: written against the adaptivecards v3 API but NOT executed in the build environment
 * (npm was unreachable). Run test/e2e with `adaptivecards` installed before relying on it.
 */
import type { CardActionInvocation, CardRenderContext, CardRenderer, RenderedCard } from './renderer';
import { DEFAULT_THEME, type ResolvedTheme } from '../ui/theme';

/* eslint-disable @typescript-eslint/no-explicit-any */
type AdaptiveCardsModule = any;

export interface SdkRendererOptions {
  theme?: Partial<ResolvedTheme>;
}

export function buildHostConfig(theme: ResolvedTheme): Record<string, unknown> {
  const colors = (strong: string, subtle: string) => ({ default: strong, subtle });
  const foreground = {
    default: colors(theme.text, theme.textMuted),
    accent: colors(theme.brand, theme.brand),
    good: colors(theme.good, theme.good),
    warning: colors(theme.warning, theme.warning),
    attention: colors(theme.attention, theme.attention),
    dark: colors(theme.text, theme.textMuted),
    light: colors(theme.surface, theme.surfaceAlt),
  };
  return {
    fontFamily: theme.fontFamily,
    supportsInteractivity: true,
    spacing: { small: 4, default: 8, medium: 16, large: 24, extraLarge: 32, padding: 12 },
    separator: { lineThickness: 1, lineColor: theme.border },
    fontSizes: { small: 12, default: 14, medium: 16, large: 20, extraLarge: 24 },
    fontWeights: { lighter: 300, default: 400, bolder: 600 },
    containerStyles: {
      default: { backgroundColor: theme.surface, foregroundColors: foreground },
      emphasis: { backgroundColor: theme.surfaceSunken, foregroundColors: foreground },
      accent: { backgroundColor: theme.brandSoft, foregroundColors: foreground },
      good: { backgroundColor: theme.brandSoft, foregroundColors: foreground },
      attention: { backgroundColor: '#fdecea', foregroundColors: foreground },
      warning: { backgroundColor: '#fff4e0', foregroundColors: foreground },
    },
    actions: {
      maxActions: 4,
      spacing: 'default',
      buttonSpacing: 8,
      actionsOrientation: 'horizontal',
      actionAlignment: 'stretch',
      showCard: { actionMode: 'inline', inlineTopMargin: 12 },
    },
    inputs: { label: { requiredInputs: { suffix: '' }, optionalInputs: {} } },
    factSet: {
      title: { color: 'default', isSubtle: true, weight: 'default', wrap: true, maxWidth: 120 },
      value: { color: 'default', weight: 'default', wrap: true },
      spacing: 8,
    },
  };
}

const registered = new WeakSet<object>();

/** Registers Org.SelectableList (and Badge when the SDK lacks it) with the SDK's element registry. */
function registerCustomElements(AC: AdaptiveCardsModule): void {
  if (registered.has(AC)) return;
  registered.add(AC);

  class SelectableList extends AC.Input {
    static readonly JsonTypeName = 'Org.SelectableList';
    static readonly itemsProperty = new AC.CustomProperty(
      AC.Versions.v1_0,
      'items',
      (_sender: any, prop: any, source: any) => (Array.isArray(source[prop.name]) ? source[prop.name] : []),
      (_sender: any, prop: any, target: any, value: any, context: any) => context.serializeValue(target, prop.name, value),
      [],
    );
    static readonly valueProperty = new AC.StringProperty(AC.Versions.v1_0, 'value');

    private radios: HTMLInputElement[] = [];

    get items(): any[] {
      return this.getValue(SelectableList.itemsProperty) ?? [];
    }

    get defaultValue(): string | undefined {
      return this.getValue(SelectableList.valueProperty);
    }

    getJsonTypeName(): string {
      return SelectableList.JsonTypeName;
    }

    protected internalRender(): HTMLElement {
      const group = document.createElement('div');
      group.className = 'ac-selectable';
      group.setAttribute('role', 'radiogroup');
      const name = `sl-${Math.random().toString(36).slice(2)}`;
      this.radios = [];
      for (const option of this.items) {
        const row = document.createElement('label');
        row.className = 'ac-option';
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = name;
        radio.value = String(option.value ?? option.id ?? '');
        radio.checked = radio.value === this.defaultValue;
        radio.addEventListener('change', () => {
          this.radios.forEach((r) => r.parentElement?.classList.toggle('is-selected', r.checked));
          this.valueChanged();
        });
        const body = document.createElement('div');
        body.className = 'ac-option-body';
        const title = document.createElement('div');
        title.className = 'ac-option-title';
        title.textContent = option.title ?? radio.value;
        body.append(title);
        for (const key of ['subtitle', 'description', 'highlight', 'meta']) {
          if (!option[key]) continue;
          const line = document.createElement('div');
          line.className = `ac-option-${key === 'highlight' ? 'highlight ac-color-good' : key}`;
          line.textContent = String(option[key]);
          body.append(line);
        }
        row.append(radio, body);
        row.classList.toggle('is-selected', radio.checked);
        group.append(row);
        this.radios.push(radio);
      }
      return group;
    }

    isSet(): boolean {
      return this.radios.some((r) => r.checked);
    }

    get value(): string | undefined {
      return this.radios.find((r) => r.checked)?.value;
    }
  }

  AC.GlobalRegistry.elements.register(SelectableList.JsonTypeName, SelectableList, AC.Versions.v1_0);

  if (!AC.GlobalRegistry.elements.findByName?.('Badge')) {
    class Badge extends AC.CardElement {
      static readonly textProperty = new AC.StringProperty(AC.Versions.v1_0, 'text');
      static readonly styleProperty = new AC.StringProperty(AC.Versions.v1_0, 'style');
      getJsonTypeName(): string {
        return 'Badge';
      }
      protected internalRender(): HTMLElement {
        const span = document.createElement('span');
        span.className = `ac-badge ac-badge-${String(this.getValue(Badge.styleProperty) ?? 'default').toLowerCase()}`;
        span.textContent = this.getValue(Badge.textProperty) ?? '';
        return span;
      }
    }
    AC.GlobalRegistry.elements.register('Badge', Badge, AC.Versions.v1_0);
  }
}

export function createSdkRenderer(AC: AdaptiveCardsModule, options: SdkRendererOptions = {}): CardRenderer {
  registerCustomElements(AC);
  const hostConfig = new AC.HostConfig(buildHostConfig({ ...DEFAULT_THEME, ...options.theme }));

  return {
    name: 'adaptivecards-sdk',
    maxVersion: '1.6',
    render(cardJson: Record<string, unknown>, ctx: CardRenderContext): RenderedCard {
      AC.AdaptiveCard.onProcessMarkdown = (text: string, result: any) => {
        result.outputHtml = ctx.markdown(text);
        result.didProcess = true;
      };
      const card = new AC.AdaptiveCard();
      card.hostConfig = hostConfig;
      card.onExecuteAction = (action: any) => {
        const typeName = action.getJsonTypeName();
        if (typeName === 'Action.OpenUrl') {
          ctx.onAction({ type: 'Action.OpenUrl', url: action.url, title: action.title, data: {}, actionData: {} });
          return;
        }
        if (typeName !== 'Action.Submit' && typeName !== 'Action.Execute') return;
        const merged = action.data && typeof action.data === 'object' ? action.data : { value: action.data };
        const invocation: CardActionInvocation = {
          type: typeName,
          title: action.title,
          verb: action.verb,
          data: { ...merged },
          // keepActive and other flags come from the action's own data, which the SDK merges with inputs.
          actionData: { ...merged },
        };
        ctx.onAction(invocation);
      };
      card.parse(cardJson);
      const element: HTMLElement = card.render() ?? document.createElement('div');
      element.classList.add('ac-card', 'ac-sdk');
      return {
        element,
        setDisabled(disabled: boolean) {
          element.classList.toggle('ac-disabled', disabled);
          element.querySelectorAll('button, input, select, textarea').forEach((node) => {
            (node as HTMLInputElement).disabled = disabled;
          });
        },
      };
    },
  };
}
