/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Monochrome accent — the UI is deliberately near-grayscale (white/
        // near-black), so "brand" here means "primary ink", not a hue.
        brand: {
          50: "#f4f4f5",
          500: "#3f3f46",
          600: "#18181b",
          700: "#000000",
        },
      },
    },
  },
  plugins: [],
};
