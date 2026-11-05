import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const TOKENS = {};
for (const match of css.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) TOKENS[match[1]] = match[2];

function srgbToLin(value) {
  const s = value / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
function lum(color) {
  const value = color.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => srgbToLin(parseInt(value.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a, b) {
  const [la, lb] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (la + 0.05) / (lb + 0.05);
}

const PAIRS = [
  ["fg-0", "bg-0", "页面标题", 4.5],
  ["fg-0", "bg-2", "卡片正文", 4.5],
  ["fg-1", "bg-3", "次级区域正文", 4.5],
  ["fg-2", "bg-2", "卡片辅助文本", 4.5],
  ["fg-2", "bg-0", "页面辅助文本", 4.5],
  ["fg-3", "bg-2", "小字号说明", 4.5],
  ["fg-2", "bg-4", "悬停区域文本", 4.5],
  ["cyan", "bg-2", "低饱和蓝强调", 4.5],
  ["cyan-2", "blue-soft", "导航选中与蓝色徽章", 4.5],
  ["amber", "amber-soft", "警告文本", 4.5],
  ["mint", "mint-soft", "成功文本", 4.5],
  ["red", "red-soft", "错误文本", 4.5],
  ["white", "primary", "主按钮文字", 4.5],
  ["fg-1", "blue-soft", "蓝色区域正文", 4.5],
];

let fails = 0;
console.log("前景        背景        比值   需要  判定  用途");
for (const [fg, bg, use, need] of PAIRS) {
  const value = ratio(TOKENS[fg], TOKENS[bg]);
  const ok = value >= need;
  if (!ok) fails++;
  console.log(`${fg.padEnd(11)} ${bg.padEnd(11)} ${value.toFixed(2).padStart(5)} ${String(need).padStart(5)}  ${ok ? "ok  " : "FAIL"}  ${use}`);
}
console.log(fails ? `\n${fails} 项不达标` : "\n全部达标（WCAG AA）");
process.exit(fails ? 1 : 0);