import { html } from "../html.js";
import { Ico } from "../icons.js";

export function FixTimeline({ fixes }) {
  if (!fixes || !fixes.length) {
    return html`<div class="empty"><span class="empty-icon"><${Ico} name="clock" size=${19} /></span><div class="empty-title">尚无执行记录</div><div class="empty-desc">确认执行修复后，这里会记录每次参数变更、影响范围、预算消耗和回归结果。</div></div>`;
  }
  return html`<ol class="timeline" aria-label="修复与回归记录">${fixes.map((fix) => {
    const passed = fix.regression_passed === true && !fix.rolled_back;
    const status = fix.rolled_back ? "已回滚" : passed ? "回归通过" : "待验证";
    return html`<li class=${`timeline-item ${fix.rolled_back ? "is-rolled" : ""}`}>
      <div class="timeline-head"><span class="tool-label"><${Ico} name="bolt" size=${13} />局部参数修复器</span><span class="timeline-id">${fix.fix_id}</span><span class=${`badge ${fix.rolled_back ? "sev-medium" : passed ? "ok" : ""}`}>${status}</span><span class="badge">预算 #${fix.budget_used}</span></div>
      <div class="changes">${(fix.changes || []).map((change) => html`<span class="change-pill"><span>${change.param}</span><span class="was">${change.old}</span><span aria-hidden="true">→</span><span class="now">${change.new}</span></span>`)}</div>
      ${fix.affected_features && fix.affected_features.length ? html`<div class="affected"><span class="label">重建特征</span>${fix.affected_features.map((feature) => html`<span class="tag">${feature}</span>`)}</div>` : null}
      ${fix.affected_constraints && fix.affected_constraints.length ? html`<div class="affected"><span class="label">回归约束</span>${fix.affected_constraints.map((constraint) => html`<span class="tag">${constraint}</span>`)}</div>` : null}
      ${fix.note ? html`<div class="timeline-meta">${fix.note}</div>` : null}
    </li>`;
  })}</ol>`;
}