/**
 * Minimal Adaptive Cards Templating engine, used by the mock relay only.
 * The real Agent relay should use Microsoft's `adaptivecards-templating` package.
 *
 * Supports: ${expr} interpolation, `$data` (object scope or array repeat), `$when`, `$root`,
 * `$index`, member/index access, string/number/boolean literals, == != < > <= >= && || !,
 * and functions count(), if(), concat(), toUpper().
 */

type Scope = { data: unknown; root: unknown; index?: number };

// ------------------------------------------------------------------ expressions

type Token = { kind: 'num' | 'str' | 'id' | 'op' | 'punc'; value: string };

function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i += 1;
    } else if (/[0-9]/.test(c)) {
      let j = i;
      while (j < src.length && /[0-9.]/.test(src[j])) j += 1;
      tokens.push({ kind: 'num', value: src.slice(i, j) });
      i = j;
    } else if (c === "'" || c === '"') {
      let j = i + 1;
      let out = '';
      while (j < src.length && src[j] !== c) {
        if (src[j] === '\\' && j + 1 < src.length) j += 1;
        out += src[j];
        j += 1;
      }
      tokens.push({ kind: 'str', value: out });
      i = j + 1;
    } else if (/[A-Za-z_$]/.test(c)) {
      let j = i;
      while (j < src.length && /[A-Za-z0-9_$]/.test(src[j])) j += 1;
      tokens.push({ kind: 'id', value: src.slice(i, j) });
      i = j;
    } else {
      const two = src.slice(i, i + 2);
      if (['==', '!=', '<=', '>=', '&&', '||'].includes(two)) {
        tokens.push({ kind: 'op', value: two });
        i += 2;
      } else if ('<>!'.includes(c)) {
        tokens.push({ kind: 'op', value: c });
        i += 1;
      } else if ('.[](),'.includes(c)) {
        tokens.push({ kind: 'punc', value: c });
        i += 1;
      } else {
        throw new Error(`Unexpected character '${c}' in expression: ${src}`);
      }
    }
  }
  return tokens;
}

const FUNCTIONS: Record<string, (...args: unknown[]) => unknown> = {
  count: (x) => (Array.isArray(x) ? x.length : typeof x === 'string' ? x.length : 0),
  if: (c, a, b) => (c ? a : b),
  concat: (...xs) => xs.map((x) => (x ?? '') as string).join(''),
  toUpper: (x) => String(x ?? '').toUpperCase(),
};

class Parser {
  private pos = 0;
  constructor(
    private readonly tokens: Token[],
    private readonly scope: Scope,
  ) {}

  parse(): unknown {
    const value = this.or();
    if (this.pos < this.tokens.length) throw new Error('Unexpected trailing tokens');
    return value;
  }

  private peek(value?: string): Token | undefined {
    const t = this.tokens[this.pos];
    return value === undefined || t?.value === value ? t : undefined;
  }

  private take(value?: string): Token {
    const t = this.tokens[this.pos];
    if (!t || (value !== undefined && t.value !== value)) throw new Error(`Expected ${value ?? 'token'}`);
    this.pos += 1;
    return t;
  }

  private or(): unknown {
    let left = this.and();
    while (this.peek('||')) {
      this.take();
      const right = this.and();
      left = Boolean(left) || Boolean(right);
    }
    return left;
  }

  private and(): unknown {
    let left = this.compare();
    while (this.peek('&&')) {
      this.take();
      const right = this.compare();
      left = Boolean(left) && Boolean(right);
    }
    return left;
  }

  private compare(): unknown {
    const left = this.unary();
    const op = this.tokens[this.pos];
    if (op?.kind === 'op' && ['==', '!=', '<', '>', '<=', '>='].includes(op.value)) {
      this.take();
      const right = this.unary() as never;
      const l = left as never;
      switch (op.value) {
        case '==':
          return l === right;
        case '!=':
          return l !== right;
        case '<':
          return l < right;
        case '>':
          return l > right;
        case '<=':
          return l <= right;
        default:
          return l >= right;
      }
    }
    return left;
  }

  private unary(): unknown {
    if (this.peek('!')) {
      this.take();
      return !this.unary();
    }
    return this.postfix();
  }

  private postfix(): unknown {
    let value = this.primary();
    for (;;) {
      if (this.peek('.')) {
        this.take();
        const name = this.take().value;
        value = value == null ? undefined : (value as Record<string, unknown>)[name];
      } else if (this.peek('[')) {
        this.take();
        const key = this.or();
        this.take(']');
        value = value == null ? undefined : (value as Record<string, unknown>)[key as string];
      } else {
        return value;
      }
    }
  }

  private primary(): unknown {
    const t = this.take();
    if (t.kind === 'num') return Number(t.value);
    if (t.kind === 'str') return t.value;
    if (t.value === '(') {
      const v = this.or();
      this.take(')');
      return v;
    }
    if (t.kind === 'id') {
      if (t.value === 'true') return true;
      if (t.value === 'false') return false;
      if (t.value === 'null') return null;
      if (this.peek('(')) {
        this.take('(');
        const args: unknown[] = [];
        while (!this.peek(')')) {
          args.push(this.or());
          if (this.peek(',')) this.take(',');
        }
        this.take(')');
        const fn = FUNCTIONS[t.value];
        if (!fn) throw new Error(`Unknown function ${t.value}`);
        return fn(...args);
      }
      if (t.value === '$root') return this.scope.root;
      if (t.value === '$data') return this.scope.data;
      if (t.value === '$index') return this.scope.index;
      const data = this.scope.data as Record<string, unknown> | undefined;
      return data == null ? undefined : data[t.value];
    }
    throw new Error(`Unexpected token ${t.value}`);
  }
}

export function evaluate(expression: string, scope: Scope): unknown {
  return new Parser(tokenize(expression), scope).parse();
}

// ------------------------------------------------------------------ expansion

const WHOLE = /^\$\{([^{}]+)\}$/;
const PART = /\$\{([^{}]+)\}/g;

function bindString(value: string, scope: Scope): unknown {
  const whole = value.match(WHOLE);
  if (whole) return evaluate(whole[1], scope);
  return value.replace(PART, (_m, expr: string) => {
    const v = evaluate(expr, scope);
    return v === undefined || v === null ? '' : String(v);
  });
}

function expandNode(node: unknown, scope: Scope): unknown[] {
  if (Array.isArray(node)) return [node.flatMap((child) => expandNode(child, scope))];
  if (typeof node === 'string') return [bindString(node, scope)];
  if (!node || typeof node !== 'object') return [node];

  const obj = node as Record<string, unknown>;
  if ('$data' in obj) {
    const { $data, ...rest } = obj;
    const bound = typeof $data === 'string' ? bindString($data, scope) : $data;
    if (Array.isArray(bound)) {
      return bound.flatMap((item, index) => expandNode(rest, { data: item, root: scope.root, index }));
    }
    return expandNode(rest, { data: bound, root: scope.root });
  }
  if ('$when' in obj) {
    const { $when, ...rest } = obj;
    const ok = typeof $when === 'string' ? bindString($when, scope) : $when;
    return ok ? expandNode(rest, scope) : [];
  }
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const [expanded] = expandNode(value, scope);
    out[key] = expanded;
  }
  return [out];
}

/** Binds a template to data, returning a plain Adaptive Card. */
export function expandTemplate<T = Record<string, unknown>>(template: unknown, data: unknown): T {
  const [result] = expandNode(template, { data, root: data });
  return result as T;
}
