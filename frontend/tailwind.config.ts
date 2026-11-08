import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        panel: '#0b1220',
        panelAlt: '#111a2e',
      },
    },
  },
  plugins: [],
};

export default config;
