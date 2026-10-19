#!/usr/bin/env node
/**
 * StoneVast Genesis NFT 批量生成器
 * 风格统一：矿石切片 + 芯片质感 + 橙色光脉（与 assets/nft-001.svg 一致）
 * 变化点：矿脉走向/数量、切面碎光线、光晕强度、橙色系微调
 * 可复现：seed = 编号，同编号永远生成同图
 * 运行：node tools/generate-nft.js
 */
const fs = require('fs');
const path = require('path');

// 种子随机（mulberry32）——确定性，可复现
function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 切面多边形顶点（与 #001 相同的板形，保持统一轮廓）
const CUT = [[512,232],[640,292],[700,410],[676,540],[574,652],[456,682],[352,608],[310,486],[342,354],[420,272]];

function ptInside() {
  // 在切面内取近似随机点（用质心+半径收缩的凸组合）
  const cx = 505, cy = 462;
  const ang = Math.random() * Math.PI * 2;
  const rad = 60 + Math.random() * 130;
  return [Math.round(cx + Math.cos(ang) * rad * 1.1), Math.round(cy + Math.sin(ang) * rad * 0.95)];
}

function genVeins(r) {
  const n = 4 + Math.floor(r() * 4); // 4-7 条矿脉
  const paths = [];
  for (let i = 0; i < n; i++) {
    let [x, y] = ptInside();
    const segs = 2 + Math.floor(r() * 3);
    let d = `M${x} ${y}`;
    for (let s = 0; s < segs; s++) {
      const nx = Math.max(340, Math.min(680, x + Math.round((r() - 0.35) * 150)));
      const ny = Math.max(280, Math.min(650, y + Math.round((r() - 0.5) * 130)));
      d += ` L${nx} ${ny}`;
      x = nx; y = ny;
    }
    const w = (1.5 + r() * 3.5).toFixed(1);
    const op = (0.35 + r() * 0.6).toFixed(2);
    paths.push(`    <path d="${d}" stroke-width="${w}" opacity="${op}"/>`);
  }
  return paths.join('\n');
}

function genChips(r) {
  const n = 2 + Math.floor(r() * 3);
  const lines = [];
  for (let i = 0; i < n; i++) {
    const [x1, y1] = ptInside();
    const x2 = Math.max(340, Math.min(680, x1 + Math.round((r() - 0.5) * 120)));
    const y2 = Math.max(280, Math.min(650, y1 + Math.round((r() - 0.5) * 100)));
    lines.push(`    <path d="M${x1},${y1} L${x2},${y2}"/>`);
  }
  return lines.join('\n');
}

function warmShift(r, base, delta) {
  // 在橙色系内微调 (#f0a35e 基准附近)
  const c = parseInt(base.slice(1), 16);
  let R = (c >> 16) & 255, G = (c >> 8) & 255, B = c & 255;
  const d = Math.round((r() - 0.5) * delta);
  R = Math.max(180, Math.min(255, R + d));
  G = Math.max(100, Math.min(200, G + Math.round(d * 0.6)));
  const hex = v => v.toString(16).padStart(2, '0');
  return `#${hex(R)}${hex(G)}${hex(B)}`;
}

function generate(id) {
  const r = rng(id * 7919 + 13);
  const num = String(id).padStart(3, '0');
  const c1 = warmShift(r, '#ffd7a8', 40);
  const c2 = warmShift(r, '#f0a35e', 30);
  const c3 = warmShift(r, '#b9631f', 36);
  const glowOp = (0.06 + r() * 0.09).toFixed(2);
  const ringOp = (0.10 + r() * 0.12).toFixed(2);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <radialGradient id="bg" cx="50%" cy="38%" r="72%">
      <stop offset="0%" stop-color="#1a1f2b"/>
      <stop offset="60%" stop-color="#0f131b"/>
      <stop offset="100%" stop-color="#0a0d12"/>
    </radialGradient>
    <linearGradient id="vein" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${c1}"/>
      <stop offset="45%" stop-color="${c2}"/>
      <stop offset="100%" stop-color="${c3}"/>
    </linearGradient>
    <linearGradient id="rock" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#2b3140"/>
      <stop offset="100%" stop-color="#161a22"/>
    </linearGradient>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="9" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="soft"><feGaussianBlur stdDeviation="26"/></filter>
  </defs>
  <rect width="1024" height="1024" fill="url(#bg)"/>
  <ellipse cx="512" cy="470" rx="330" ry="300" fill="${c2}" opacity="${glowOp}" filter="url(#soft)"/>
  <circle cx="512" cy="470" r="332" fill="none" stroke="${c2}" stroke-opacity="${ringOp}" stroke-width="1.5"/>
  <circle cx="512" cy="470" r="300" fill="none" stroke="#2b3140" stroke-width="1"/>
  <polygon points="512,196 664,262 742,404 716,566 596,702 452,740 322,650 268,494 306,336 396,240" fill="url(#rock)" stroke="#3a4152" stroke-width="2"/>
  <polygon points="512,232 640,292 700,410 676,540 574,652 456,682 352,608 310,486 342,354 420,272" fill="#12161e" stroke="#252b38" stroke-width="1.5"/>
  <g fill="none" stroke="url(#vein)" stroke-linecap="round" filter="url(#glow)">
${genVeins(r)}
  </g>
  <g stroke="${c2}" stroke-opacity="0.35" fill="none" stroke-width="1">
${genChips(r)}
  </g>
  <text x="512" y="836" text-anchor="middle" fill="#e9edf4" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="30" font-weight="700" letter-spacing="6">STONEVAST GENESIS</text>
  <text x="512" y="876" text-anchor="middle" fill="#8b93a7" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16" letter-spacing="4">REAL HASHRATE · REAL REVENUE</text>
  <text x="512" y="936" text-anchor="middle" fill="${c2}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="44" font-weight="800" letter-spacing="8">#${num}</text>
  <g stroke="${c2}" stroke-opacity="0.5" stroke-width="2" fill="none">
    <path d="M64 128 L64 64 L128 64"/>
    <path d="M896 64 L960 64 L960 128"/>
    <path d="M64 896 L64 960 L128 960"/>
    <path d="M960 896 L960 960 L896 960"/>
  </g>
</svg>
`;
}

const outDir = path.join(__dirname, '..', 'assets', 'nft');
fs.mkdirSync(outDir, { recursive: true });
for (let i = 1; i <= 100; i++) {
  const file = path.join(outDir, `nft-${String(i).padStart(3, '0')}.svg`);
  fs.writeFileSync(file, generate(i));
}
console.log('OK: 100 Genesis NFTs generated to', outDir);
