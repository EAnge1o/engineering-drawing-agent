/**
 * 前端语法自检（开发用）。对所有源文件执行 node --check。
 * 运行：node scripts/check-syntax.mjs
 */
import { readdirSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const roots = ["src", "src/components"];
const files = [];
for (const dir of roots) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isFile() && name.endsWith(".js")) files.push(p);
  }
}

let failed = 0;
for (const f of files) {
  try {
    execFileSync(process.execPath, ["--check", f], { stdio: "pipe" });
  } catch (e) {
    failed++;
    console.log(`  FAIL ${f}`);
    console.log(String(e.stderr || e.message).split("\n").slice(0, 4).join("\n"));
  }
}

console.log(failed ? `\n${failed} 个文件语法错误` : `\n语法检查通过（${files.length} 个文件）`);
process.exit(failed ? 1 : 0);