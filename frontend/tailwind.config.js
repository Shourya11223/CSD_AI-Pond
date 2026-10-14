/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        terrain: {
          50: '#f7f6f2',
          100: '#ede9df',
          200: '#dedbc2',
          300: '#c9c49e',
          400: '#afa876',
          500: '#9a8d5a',
          600: '#7e7247',
          700: '#665a3a',
          800: '#534a31',
          900: '#453e2a',
          950: '#262115',
        },
        water: {
          50: '#eef7ff',
          100: '#d9edff',
          200: '#bcdfff',
          300: '#8fc9ff',
          400: '#59a7ff',
          500: '#3689ff',
          600: '#1d6ef5',
          700: '#1757e0',
          800: '#1a47bb',
          900: '#1c3d96',
          950: '#132759',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'pulse-slow': 'pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
