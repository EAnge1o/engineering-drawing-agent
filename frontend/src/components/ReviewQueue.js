import { html } from "../html.js";
import { Ico } from "../icons.js";

const REASONS = {
  budget_exhausted: "修复预算已用尽",
  low_confidence: "解析置信度不足",
  not_fixable: "当前问题不适合自动修复",
  propose_error: "修复候选生成失败",
  no_safe_candidate: "未找到满足安全约束的候选方案",
};

export function ReviewQueue({ task, result, onExport, busy }) {
  const pending = result
    ? (result.pending_confirmation || []).map((item) => ({ title: item.issue, reason: REASONS[item.reason] || item.reason, detail: item.detail || (item.confidence != null ? `置信度 ${Number(item.confidence).toFixed(2)}` : "请结合原始证据人工复核") }))
    : (((task && task.parse && task.parse.pending) || []).map((id) => ({ title: id, reason: "该参数需要人工确认", detail: "请核对图纸来源与尺寸证据后再继续" })));
  if (!pending.length) {
    return html`<div class="empty"><span class="empty-icon"><${Ico} name=${task ? "check" : "user"} size=${19} /></span><div class="empty-title">${task ? "当前无需人工处理" : "暂无待处理事项"}</div><div class="empty-desc">${task ? "解析与修复过程中出现的待确认项会集中在这里。" : "创建任务后，低置信度参数和高风险修复会进入人工处理队列。"}</div></div>`;
  }
  return html`<div class="review-list">
    ${pending.map((item) => html`<div class="review-item">
      <div class="review-head"><span class="review-title">${item.title}</span><span class="badge sev-medium">待确认</span></div>
      <div class="review-reason">${item.reason}</div><div class="review-detail">${item.detail}</div>
    </div>`)}
    <div class="review-foot">自动流程不会绕过这些事项。${result ? "可导出报告，交由工程人员复核。" : "请核对参数证据与原始图纸。"}</div>
    ${result ? html`<button class="btn" disabled=${busy === "export"} onClick=${onExport}><${Ico} name="download" size=${14} />导出待处理记录</button>` : null}
  </div>`;
}