import { html } from "../html.js";
import { Ico } from "../icons.js";

export function AgentStatus({ task, result, compare, geometry, busy, exportedAt, explanation, onExplain }) {
  const issues = (result && result.issues) || (task && task.issues) || [];
  const state = busy
    ? busy === "parse" ? "正在解析图纸" : busy === "fix" ? "正在执行修复闭环" : busy === "export" ? "正在生成证据报告" : "正在生成任务说明"
    : result ? result.state === "DONE" ? "任务已完成" : "需要人工处理"
    : task ? "审查完成，等待修复" : "等待新任务";
  const tone = busy ? "is-running" : result ? result.state === "DONE" ? "is-done" : "is-warn" : "";
  const desc = busy
    ? "操作正在服务端执行，完成后会自动刷新任务结果。"
    : result
      ? result.state === "DONE" ? "修复与回归验证已完成，可以导出完整证据。" : "自动修复已停止，请先处理下方待确认事项。"
      : task ? "解析和确定性审查已完成，下一步由你确认是否执行修复。" : "上传图纸或运行内置蓝图，Agent 将创建可追溯任务。";
  const steps = [
    { name: "图纸解析器", done: !!task, running: busy === "parse", note: task ? `${((task.parse && task.parse.fields) || []).length} 项参数 · ${(task.parse && task.parse.overall_mode) || "已解析"}` : "等待输入" },
    { name: "确定性规则引擎", done: !!task, running: false, note: task ? `完成 ${issues.length} 项问题分类` : "等待解析结果" },
    { name: "局部参数修复器", done: !!result, running: busy === "fix", warn: !!result && result.state !== "DONE", note: result ? `使用预算 ${result.budget.used}/${result.budget.total} · ${result.state}` : "等待人工启动" },
    { name: "几何重建与回归验证", done: !!result && !!geometry, running: busy === "fix", warn: !!result && !compare, note: result ? compare ? `对比 ${compare.changed_params.length} 项参数变更` : "修复已完成，对比数据不可用" : "等待修复执行" },
    { name: "证据报告生成器", done: !!exportedAt, running: busy === "export", note: exportedAt ? "报告与证据清单已导出" : result ? "等待导出" : "等待验证结果" },
  ];
  return html`
    <div class="section-stack">
      <div class=${`run-state ${tone}`}>
        <span class="run-icon"><${Ico} name=${result && result.state === "DONE" && !busy ? "check" : "spark"} size=${18} /></span>
        <div class="run-copy"><div class="run-title">${state}</div><div class="run-desc">${desc}</div></div>
        ${busy ? html`<span class="spinner" aria-label="执行中"></span>` : null}
      </div>
      <ol class="agent-steps" aria-label="Agent 工具执行阶段">
        ${steps.map((step, i) => {
          const cls = step.done ? "is-done" : step.warn ? "is-warn" : step.running ? "is-running" : "";
          return html`<li class=${`agent-step ${cls}`}>
            <span class="agent-marker">${step.done ? "✓" : step.running ? "···" : i + 1}</span>
            <div><div class="agent-name">${step.name}</div><div class="agent-note">${step.note}</div></div>
          </li>`;
        })}
      </ol>
      ${result ? html`<div class="section-footer"><button class="btn btn-accent" disabled=${!!busy} onClick=${onExplain}><${Ico} name="spark" size=${14} />${busy === "explain" ? "正在生成…" : explanation ? "重新生成任务说明" : "生成任务说明"}</button></div>` : null}
      ${explanation ? html`<div class="explanation">
        <div class="explanation-head"><span>任务说明</span><span class="badge">${explanation.source === "llm" ? "模型生成" : "确定性摘要"}</span></div>
        <p>${explanation.summary}</p><p>${explanation.changes}</p><p>${explanation.explanation}</p>
      </div>` : null}
    </div>
  `;
}