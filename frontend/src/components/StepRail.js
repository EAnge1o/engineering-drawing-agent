import { html } from "../html.js";

const STEPS = [
  { key: "parse", text: "解析图纸" },
  { key: "audit", text: "确定性审查" },
  { key: "fix", text: "局部修复" },
  { key: "verify", text: "回归验证" },
  { key: "export", text: "导出证据" },
];

export function StepRail({ stage, hasTask, busy, exported }) {
  let doneCount = 0;
  if (hasTask) doneCount = 2;
  if (stage >= 2) doneCount = stage >= 3 ? 4 : 3;
  if (exported) doneCount = 5;
  if (busy === "parse") doneCount = 0;
  const active = Math.min(doneCount, STEPS.length - 1);
  return html`
    <nav class="steps" aria-label="工作流步骤">
      ${STEPS.map((step, i) => {
        const isActive = i === active && !exported;
        const isDone = i < doneCount;
        const isRunning = (busy === "parse" && i === 0) || (busy === "fix" && i === 2) || (busy === "export" && i === 4);
        return html`<div class=${`step ${isActive ? "is-active" : ""} ${isDone ? "is-done" : ""} ${isRunning ? "is-running" : ""}`} aria-current=${isActive ? "step" : null}>
          <span class="step-dot" aria-hidden="true">${isDone ? "✓" : isRunning ? "···" : i + 1}</span>
          <span class="step-text">${step.text}</span>
        </div>`;
      })}
    </nav>
  `;
}