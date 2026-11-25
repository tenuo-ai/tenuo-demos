/** @type {import('tailwindcss').Config} */

// Tenuo brand (Brand Guidelines v1.0, as implemented in the website's
// docs/assets/brand.css), with a navy dark theme (default) and a light theme.
//
// The dashboard's existing utility classes keep their names; each Tailwind
// scale is re-expressed in brand colours, and every step is a CSS variable
// defined per theme in src/theme.css:
//
//   gray    -> neutrals (navy in dark; mist/white, Obsidian and Graphite in light)
//   blue    -> Signal Blue          green -> ok     red -> bad     orange -> warn
//   amber, yellow -> gold           purple -> violet               cyan, sky -> cyan
//
// In both themes, 600-700 are solid fills that take white text, 300-400 are
// coloured text, and 800-950 are rules and washes. `white` stays white in both
// themes; it is used for text on solid fills.

const STEPS = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950']

const scale = (name) =>
  Object.fromEntries(STEPS.map((s) => [s, `rgb(var(--c-${name}-${s}) / <alpha-value>)`]))

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        gray: scale('gray'),
        blue: scale('blue'),
        green: scale('green'),
        red: scale('red'),
        orange: scale('orange'),
        amber: scale('gold'),
        yellow: scale('gold'),
        purple: scale('violet'),
        cyan: scale('cyan'),
        sky: scale('cyan'),
        white: '#FFFFFF',
        // Header band: Authority Navy in dark, white in light.
        navy: {
          DEFAULT: 'rgb(var(--c-navy) / <alpha-value>)',
          6: 'rgb(var(--c-navy-6) / <alpha-value>)',
          4: 'rgb(var(--c-navy-4) / <alpha-value>)',
        },
      },
      fontFamily: {
        display: ['"TASA Explorer"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        sans: ['Lato', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        mono: ['"DM Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // Panel text one step up from Tailwind's defaults (12/14 px), since Lato
      // reads smaller than the monospace the dashboard used before.
      fontSize: {
        xs: ['0.8125rem', { lineHeight: '1.25rem' }],
        sm: ['0.9375rem', { lineHeight: '1.375rem' }],
      },
      borderRadius: {
        DEFAULT: '6px',
        lg: '10px',
      },
    },
  },
  plugins: [],
}
