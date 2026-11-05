import { useState } from "preact/hooks";
import { html } from "../html.js";
import { Ico } from "../icons.js";

const LAYER_LABEL = { geometric: "几何约束", drawing_model: "图纸一致性", design_intent: "设计意图" };
const FILTERS = [{ id: "all", text: "全部" }, { id: "open", text: "待处理" }, { id: "resolved", text: "已解决" }];

export function IssueList({ issues, onSelect, remainingIds }) {
  const [filter, setFilter] = useState("all");
  const isResolved = (issue) => !!remainingIds && !!issue.constraint_id && !remainingIds.includes(issue.constraint_id);
  const all = issues || [];
  const visible = all.filter((issue) => filter === "all" || (filter === "resolved" ? isResolved(issue) : !isResolved(issue)));
  if (!all.length) {
    return html`<div class="empty"><span class="empty-icon"><${Ico} name="shield" size=${19} /></span><div class="empty-title">暂无审查问题</div><div class="empty-desc">解析图纸后，规则引擎会在这里列出几何冲突、图纸一致性与设计意图问题。</div></div>`;
  }
  return html`<div>
    <div class="issue-filters"><span class="seg" role="group" aria-label="筛选审查问题">${FILTERS.map((item) => html`<button class=${`seg-item ${filter === item.id ? "is-on" : ""}`} aria-pressed=${filter === item.id} onClick=${() => setFilter(item.id)}>${item.text}</button>`)}</span><span class="filter-count">显示 ${visible.length} / ${all.length} 项</span></div>
    ${visible.length ? html`<ul class="issues" aria-label="审查问题列表">${visible.map((issue) => {
      const resolved = isResolved(issue);
      return html`<li class=${`issue sev-${issue.severity} ${resolved ? "is-resolved" : ""}`}>
        <div class="issue-top"><span class=${`badge sev-${issue.severity}`}>${issue.severity}</span><span class="issue-id">${issue.constraint_id || issue.code}</span>${resolved ? html`<span class="badge ok">已解决</span>` : null}<span class="badge">${LAYER_LABEL[issue.layer] || issue.layer}</span><span class="issue-layer conf-bar"><span class="conf-track" aria-hidden="true"><span class=${`conf-fill ${issue.confidence < 0.55 ? "is-crit" : issue.confidence < 0.85 ? "is-low" : ""}`} style=${`width:${Math.round((issue.confidence || 0) * 100)}%`}></span></span><span class="mono">${(issue.confidence || 0).toFixed(2)}</span></span></div>
        <div class="issue-evidence">${(issue.evidence || []).join("；") || "（无附加证据）"}</div>
        ${onSelect && issue.fix_hint ? html`<div class="issue-actions"><button class="btn btn-small" onClick=${() => onSelect(issue)}><${Ico} name="target" size=${13} />在模型中定位</button></div>` : null}
      </li>`;
    })}</ul>` : html`<div class="empty"><div class="empty-title">当前筛选下没有问题</div><div class="empty-desc">切换到其他状态查看完整审查结果。</div></div>`}
  </div>`;
}