/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        synapse: {
          bg: "#08090A",
          surface: "#0F1011",
          "surface-2": "#16181A",
          "surface-3": "#1D2023",
          border: "#212327",
          "border-strong": "#2C3034",
          cyan: "#2AA8E0",
          "cyan-dim": "#1B7FA8",
          green: "#3FB950",
          red: "#F0524A",
          amber: "#D29922",
          purple: "#a855f7",
          muted: "#6A7076",
          text: "#E8EAED",
          "text-2": "#9BA1A8",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "glow": "glow 2s ease-in-out infinite alternate",
        "scan": "scan 2s linear infinite",
      },
      keyframes: {
        glow: {
          "0%": { boxShadow: "0 0 5px #00d4ff44" },
          "100%": { boxShadow: "0 0 20px #00d4ff88, 0 0 40px #00d4ff22" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
      },
    },
  },
  plugins: [],
};
