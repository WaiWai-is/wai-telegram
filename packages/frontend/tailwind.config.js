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
      },
    },
  },
  plugins: [],
}
