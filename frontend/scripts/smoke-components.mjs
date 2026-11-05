import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>", { url: "http://localhost:8000/", pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
global.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);
global.URL = dom.window.URL;
global.Blob = dom.window.Blob;

const { render } = await import("preact");
const { html } = await import("../src/html.js");
const modulePaths = {
  TopBar: "../src/components/TopBar.js",
  Sidebar: "../src/components/Sidebar.js",
  StepRail: "../src/components/StepRail.js",
  IssueList: "../src/components/IssueList.js",
  FixTimeline: "../src/components/FixTimeline.js",
  DiffCompare: "../src/components/DiffCompare.js",
  Inspector: "../src/components/Inspector.js",
  DropZone: "../src/components/DropZone.js",
  Stat: "../src/components/Stat.js",
  Toast: "../src/components/Toast.js",
  AgentStatus: "../src/components/AgentStatus.js",
  ReviewQueue: "../src/components/ReviewQueue.js",
  ConfirmDialog: "../src/components/ConfirmDialog.js",
};
const mods = {};
for (const [key, path] of Object.entries(modulePaths)) mods[key] = await import(path);
const root = document.getElementById("root");
const results = [];

function check(name, node, expectSubstrings) {
  render(null, root);
  root.innerHTML = "";
  try {
    render(node, root);
    const out = root.innerHTML;
    const missing = expectSubstrings.filter((text) => !out.includes(text));
    results.push(missing.length ? { name, ok: false, why: `缺少文本: ${missing.join(" | ")}` } : { name, ok: true, bytes: out.length });
  } catch (error) {
    results.push({ name, ok: false, why: `${error.name}: ${error.message}` });
  }
}

const meta = { cadquery_available: true, llm_available: false, thresholds: { high: 0.85, low: 0.55 } };
const issues = [{ id: "issue::c_h4_inside", code: "hole_inside", layer: "geometric", severity: "high", confidence: 0.6, constraint_id: "c_h4_inside", evidence: ["孔位 (115,65) 右边距 5 < 最小 12"], fixable: true, fix_hint: { side: "right" } }];
const fixes = [{ fix_id: "fix::issue::c_h4_inside", issue_id: "issue::c_h4_inside", changes: [{ param: "hole.x4", old: 115, new: 105 }], affected_features: ["hole_h4"], affected_constraints: ["c_h4_inside", "c_sp_h2h4"], regression_passed: true, rolled_back: false, budget_used: 1, note: "" }];
const task = { task_id: "T-001", parse: { overall_mode: "A1", pending: [], notes: ["孔位边距不一致（疑似标注冲突）：孔 h4"], fields: [{ id: "plate.L", value: 120, confidence: 0.95, status: "observed", mode: "A0", needs_confirm: false }, { id: "hole.x4", value: 115, confidence: 0.6, status: "observed", mode: "A1", needs_confirm: true }] } };
const result = { state: "DONE", issues, fixes, resolved: 1, remaining: [], pending_confirmation: [], budget: { used: 1, total: 5 } };
const compare = { before_issue_count: 1, after_issue_count: 0, changed_params: [{ param: "hole.x4", before: 115, after: 105, delta: -10 }], resolved: ["c_h4_inside"], remaining: [] };
const geometry = { kernel: "cadquery", bbox: { length: 120, width: 80, height: 6 }, holes: [], hole_count: 4 };

check("TopBar", html`<${mods.TopBar.TopBar} meta=${meta} task=${task} />`, ["工程图纸建模与自纠错", "几何内核", "任务 T-001"]);
check("Sidebar", html`<${mods.Sidebar.Sidebar} stage=${2} hasTask=${true} meta=${meta} />`, ["Sourth", "任务总览", "当前流程"]);
check("StepRail", html`<${mods.StepRail.StepRail} stage=${2} hasTask=${true} />`, ["解析图纸", "确定性审查", "局部修复", "回归验证", "导出证据"]);
check("IssueList", html`<${mods.IssueList.IssueList} issues=${issues} />`, ["c_h4_inside", "孔位", "几何约束", "0.60", "全部"]);
check("FixTimeline", html`<${mods.FixTimeline.FixTimeline} fixes=${fixes} />`, ["fix::issue::c_h4_inside", "回归通过", "115", "105", "c_sp_h2h4"]);
check("DiffCompare", html`<${mods.DiffCompare.DiffCompare} compare=${compare} />`, ["变更参数", "已解决问题", "hole.x4", "c_h4_inside"]);
check("Inspector", html`<${mods.Inspector.Inspector} task=${task} meta=${meta} />`, ["A1 辅助", "plate.L", "hole.x4", "阈值"]);
check("DropZone", html`<${mods.DropZone.DropZone} file=${null} onFile=${() => {}} />`, ["上传工程图纸", "PDF"]);
check("Stat", html`<${mods.Stat.Stat} label="审查问题" value=${3} tone="warn" />`, ["审查问题", "is-warn"]);
check("AgentStatus", html`<${mods.AgentStatus.AgentStatus} task=${task} result=${result} compare=${compare} geometry=${geometry} />`, ["任务已完成", "图纸解析器", "生成任务说明"]);
check("ReviewQueue", html`<${mods.ReviewQueue.ReviewQueue} task=${task} result=${{ ...result, pending_confirmation: [{ issue: "c_h4_inside", reason: "low_confidence", confidence: 0.6 }] }} />`, ["c_h4_inside", "解析置信度不足", "导出待处理记录"]);
check("ConfirmDialog", html`<${mods.ConfirmDialog.ConfirmDialog} open=${true} budget=${5} issueCount=${1} onCancel=${() => {}} onConfirm=${() => {}} />`, ["确认执行自动修复", "A1 辅助", "确认并执行"]);
check("Toast", html`<${mods.Toast.ToastHost} items=${[{ id: "1", tone: "ok", title: "保存成功", desc: "结果已更新" }]} dismiss=${() => {}} />`, ["保存成功", "结果已更新"]);

let failed = 0;
for (const item of results) {
  if (item.ok) console.log(`  ok   ${item.name.padEnd(14)} (${item.bytes}B)`);
  else { failed++; console.log(`  FAIL ${item.name.padEnd(14)} ${item.why}`); }
}
console.log(failed ? `\n${failed} 项失败` : `\n全部 ${results.length} 个组件渲染通过`);
process.exit(failed ? 1 : 0);