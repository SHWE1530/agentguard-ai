/** @type {import('tailwindcss').Config} */
// The theme is driven by CSS variables (see src/index.css) so the whole UI can be
// re-skinned in one place. Scales keep their dark-UI names (ink-*, slate-*, white) but
// resolve to a WHITE theme: "white" is the ink colour (near-black), slate-100 is dark text, etc.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        white: v('c-fg'),
        ink: { 950: v('ink-950'), 900: v('ink-900'), 850: v('ink-850'), 800: v('ink-800'), 700: v('ink-700'), 600: v('ink-600') },
        slate: {
          50: v('sl-50'), 100: v('sl-100'), 200: v('sl-200'), 300: v('sl-300'), 400: v('sl-400'),
          500: v('sl-500'), 600: v('sl-600'), 700: v('sl-700'), 800: v('sl-800'), 900: v('sl-900'),
        },
        safe: v('safe'), warn: v('warn'), high: v('high'), crit: v('crit'), ai: v('ai'), beam: v('beam'),
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      keyframes: {
        'fade-up': { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(220,38,38,0.35)' },
          '70%': { boxShadow: '0 0 0 10px rgba(220,38,38,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(220,38,38,0)' },
        },
      },
      animation: { 'fade-up': 'fade-up 0.35s ease-out', 'pulse-ring': 'pulse-ring 1.8s infinite' },
    },
  },
  plugins: [],
}
