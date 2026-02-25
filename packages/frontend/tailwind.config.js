/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
      colors: {
        surface: 'var(--background)',
        primary: 'var(--foreground)',
        secondary: 'var(--color-secondary)',
        tertiary: 'var(--color-tertiary)',
        border: 'var(--color-border)',
        'surface-hover': 'var(--color-surface-hover)',
        'chat-bg': 'var(--chat-bg)',
        'bubble-out': 'var(--bubble-outgoing)',
        'bubble-in': 'var(--bubble-incoming)',
        'bubble-out-text': 'var(--bubble-outgoing-text)',
        'bubble-in-text': 'var(--bubble-incoming-text)',
        timestamp: 'var(--timestamp-color)',
        'date-pill-bg': 'var(--date-pill-bg)',
        'date-pill-text': 'var(--date-pill-text)',
        'chat-list-hover': 'var(--chat-list-hover)',
        'tg-blue': 'var(--sync-button-bg)',
      },
    },
  },
  plugins: [],
}
