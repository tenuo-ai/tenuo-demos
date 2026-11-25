/** @type {import('tailwindcss').Config} */

// Tenuo brand, navy dark theme (Brand Guidelines v1.0, as implemented in the
// website's docs/assets/brand.css). The dashboard's existing utility classes
// keep their names; each Tailwind scale below is re-expressed in brand colours:
//
//   gray    -> navy neutrals: page #000A1D, surface #00133A, rules #17336D/#20427D,
//              text #FFFFFF / #DCE9FF / #AFC8F4 (dimmer steps checked for AA on navy)
//   blue    -> Signal Blue (#508FFF), with Cloud Blue #C3D9FF at the light end
//   green   -> ok (#1E9E6A, wash #0D2C24)
//   red     -> bad (#CB4141, wash #321419)
//   orange  -> warn (#B4551A)
//   amber, yellow -> gold, for the Payment Executor and warnings
//   purple  -> violet, for the Invoice Processor
//   cyan, sky -> light cyan, for chain fields
//
// 950 is the darkest step and 100 the lightest, as in Tailwind's own scales.

const navy = {
  50: '#FFFFFF',
  100: '#FFFFFF',
  200: '#DCE9FF',
  300: '#C9DBF8',
  400: '#AFC8F4',
  500: '#8FA9D6',
  600: '#7690C2',
  700: '#4F6CA3',
  800: '#17336D',
  900: '#00133A',
  950: '#000A1D',
}

const signal = {
  50: '#EEF4FF',
  100: '#EEF4FF',
  200: '#C3D9FF',
  300: '#96BCFF',
  400: '#73A5FF',
  500: '#508FFF',
  600: '#4075D4',
  700: '#305BA9',
  800: '#1D3F82',
  900: '#0F2A5E',
  950: '#081B40',
}

const ok = {
  100: '#D6F5E7', 200: '#B4ECD3', 300: '#95E3C0', 400: '#5FD3A0', 500: '#2DBB80',
  600: '#1E9E6A', 700: '#1A7F55', 800: '#176445', 900: '#12402F', 950: '#0D2C24',
}

const bad = {
  100: '#FFE3E3', 200: '#FFCACA', 300: '#FFB3B3', 400: '#FF8A8A', 500: '#E05A5A',
  600: '#CB4141', 700: '#A83838', 800: '#7A2A31', 900: '#4A1C22', 950: '#321419',
}

const warn = {
  100: '#FDE7D6', 200: '#FAD0B0', 300: '#F7B98A', 400: '#F29A5C', 500: '#D9762E',
  600: '#B4551A', 700: '#934617', 800: '#6E3514', 900: '#4A2410', 950: '#2E170A',
}

const gold = {
  100: '#FDF1D4', 200: '#FAE2A8', 300: '#F5D27E', 400: '#F0C060', 500: '#E0A93A',
  600: '#C08A22', 700: '#946A1A', 800: '#6B4D15', 900: '#45320F', 950: '#2A1F0A',
}

const violet = {
  100: '#EDEAFF', 200: '#DAD4FF', 300: '#C7BEFF', 400: '#A99BFF', 500: '#8A78F0',
  600: '#6E58D9', 700: '#5741B8', 800: '#3E2E8A', 900: '#2A1E5E', 950: '#1C1440',
}

const cyan = {
  100: '#E3F7FD', 200: '#C3EEFB', 300: '#9ADDF6', 400: '#5CC8F0', 500: '#2FAEDB',
  600: '#1F8DB5', 700: '#19708F', 800: '#135A7E', 900: '#0D3A52', 950: '#06243A',
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        gray: navy,
        blue: signal,
        green: ok,
        red: bad,
        orange: warn,
        amber: gold,
        yellow: gold,
        purple: violet,
        cyan,
        sky: cyan,
        white: '#FFFFFF',
        // Named brand tokens, for new code.
        navy: { DEFAULT: '#001848', 6: '#00133A', 4: '#14306B' },
        signal: { DEFAULT: '#508FFF', 4: '#73A5FF', 6: '#4075D4', 7: '#305BA9', text: '#96BCFF' },
        cloud: '#C3D9FF',
      },
      fontFamily: {
        display: ['"TASA Explorer"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        sans: ['Lato', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        mono: ['"DM Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '6px',
        lg: '10px',
      },
    },
  },
  plugins: [],
}
