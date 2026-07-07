import sharp from "sharp";
// 1200x630 OG card — brand teal canvas, gold VIGIL wordmark, cream tagline,
// emerald accent rule. Pure vector text (system-safe: uses generic families
// only where librsvg can resolve; wordmark drawn with monospace fallback).
const svg = `
<svg width="1200" height="630" viewBox="0 0 1200 630" xmlns="http://www.w3.org/2000/svg">
  <rect width="1200" height="630" fill="#041c1c"/>
  <rect x="0" y="0" width="1200" height="6" fill="#ffbd38"/>
  <g opacity="0.08">
    <circle cx="1050" cy="480" r="320" fill="#34d399"/>
    <circle cx="1120" cy="120" r="180" fill="#ffbd38"/>
  </g>
  <text x="80" y="180" font-family="Georgia, 'Times New Roman', serif" font-size="120" font-weight="700" letter-spacing="6" fill="#ffbd38">VIGIL</text>
  <rect x="84" y="220" width="150" height="4" fill="#34d399"/>
  <text x="80" y="310" font-family="Arial, Helvetica, sans-serif" font-size="44" font-weight="700" fill="#ffe6cb">The AI workspace that</text>
  <text x="80" y="368" font-family="Arial, Helvetica, sans-serif" font-size="44" font-weight="700" fill="#ffe6cb">thinks before it acts.</text>
  <text x="80" y="452" font-family="Arial, Helvetica, sans-serif" font-size="26" fill="#ffe6cbaa">AI council · verified departments · human-in-the-loop trade desk</text>
  <g font-family="'Courier New', monospace" font-size="22" fill="#34d399">
    <text x="80" y="545">propose → verify → approve</text>
  </g>
  <text x="80" y="588" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#ffe6cb77">vigil-ai.xyz</text>
</svg>`;
await sharp(Buffer.from(svg), { density: 150 }).resize(1200, 630).png().toFile("public/og.png");
const meta = await sharp("public/og.png").metadata();
console.log("og.png", meta.width + "x" + meta.height, Math.round((await import("node:fs")).statSync("public/og.png").size / 1024) + "KB");
