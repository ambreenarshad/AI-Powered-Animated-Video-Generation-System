/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        noir: {
          bg:     '#0f0f0f',
          bg2:    '#1a1a1a',
          bg3:    '#242424',
          border: '#2e2e2e',
          gold:   '#c9a84c',
          gold2:  '#e8c96d',
          cream:  '#f0e6cc',
          muted:  '#7a7060',
          green:  '#4caf84',
          red:    '#c94c4c',
          blue:   '#4c8caf',
          white:  '#f5f0e8',
        },
      },
      fontFamily: {
        mono:  ['"Courier New"', 'Courier', 'monospace'],
        serif: ['Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
