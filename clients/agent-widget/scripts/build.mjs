// Builds the widget bundles with esbuild.
//   dist/agent-widget.esm.js             npm entry (deps external)
//   dist/agent-widget.iife.js            CDN bundle: <script src> registers <agent-widget>, global `AgentWidget`
//   dist/agent-widget-mock.{esm,iife}.js mock relay for demos/tests, global `AgentWidgetMock`
//   dist/agent-widget-sdk-renderer.esm.js adapter for Microsoft's adaptivecards SDK
import { build } from 'esbuild';
import { readFileSync, mkdirSync, rmSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const define = { __WIDGET_VERSION__: JSON.stringify(pkg.version) };
const banner = { js: `/*! ${pkg.name} v${pkg.version} */` };
const common = { bundle: true, target: ['es2020', 'chrome100', 'safari15', 'firefox100'], define, banner, legalComments: 'none', logLevel: 'warning' };
const external = Object.keys(pkg.dependencies ?? {});

rmSync('dist', { recursive: true, force: true });
mkdirSync('dist', { recursive: true });

const results = await Promise.all([
  build({ ...common, entryPoints: ['src/index.ts'], format: 'esm', outfile: 'dist/agent-widget.esm.js', external, sourcemap: true }),
  build({ ...common, entryPoints: ['src/index.ts'], format: 'iife', globalName: 'AgentWidget', outfile: 'dist/agent-widget.iife.js', minify: true, sourcemap: true, metafile: true }),
  build({ ...common, entryPoints: ['src/mock/index.ts'], format: 'esm', outfile: 'dist/agent-widget-mock.esm.js', sourcemap: true }),
  build({ ...common, entryPoints: ['src/mock/index.ts'], format: 'iife', globalName: 'AgentWidgetMock', outfile: 'dist/agent-widget-mock.iife.js', minify: true }),
  build({ ...common, entryPoints: ['src/cards/sdk-adapter.ts'], format: 'esm', outfile: 'dist/agent-widget-sdk-renderer.esm.js' }),
  build({ ...common, entryPoints: ['src/cards/sdk-adapter.ts'], format: 'iife', globalName: 'AgentWidgetSdk', outfile: 'dist/agent-widget-sdk-renderer.iife.js' }),
]);

const iife = results[1].metafile.outputs['dist/agent-widget.iife.js'];
console.log(`built ${pkg.name} v${pkg.version} — CDN bundle ${(iife.bytes / 1024).toFixed(1)} KB (minified, before gzip)`);
