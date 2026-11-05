import { html } from "../html.js";
import { Stat } from "./Stat.js";
import { Ico } from "../icons.js";

function bar(value, max) {
  return Math.max(2, Math.round((Math.abs(value) / max) * 100));
}

export function DiffCompare({ compare, fallbackResult }) {
  const fromCompare = (compare && compare.changed_params) || [];
  const fromFixes = ((fallbackResult && fallbackResult.fixes) || []).flatMap((fix) => (fix.changes || []).map((change) => ({ param: change.param, before: change.old, after: change.new, delta: Number((change.new - change.old).toFixed(4)) })));
  const rows = fromCompare.length ? fromCompare : fromFixes;
  const resolved = (compare && compare.resolved) || [];
  const remaining = (compare && compare.remaining) || ((fallbackResult && fallbackResult.remaining) || []);
  const resolvedCount = compare ? resolved.length : ((fallbackResult && fallbackResult.resolved) || 0);
  const beforeCount = compare ? compare.before_issue_count : null;
  const afterCount = compare ? compare.after_issue_count : remaining.length;
  const estimated = !compare && !!fallbackResult;
  if (!rows.length && !compare && !((fallbackResult && fallbackResult.fixes) || []).length) {
    return html`<div class="empty"><span class="empty-icon"><${Ico} name="shield" size=${19} /></span><div class="empty-title">等待验证结果</div><div class="empty-desc">执行修复后，这里会展示问题收敛情况、参数差异和仍需关注的约束。</div></div>`;
  }
  return html`<div class="diff">
    <div class="metrics"><${Stat} label="变更参数" value=${rows.length} tone="accent" /><${Stat} label="已解决问题" value=${resolvedCount} tone="ok" /><${Stat} label="剩余问题" value=${remaining.length} tone=${remaining.length ? "warn" : "ok"} /><${Stat} label="问题总数变化" value=${beforeCount == null ? 0 : beforeCount - afterCount} tone=${beforeCount != null && beforeCount - afterCount > 0 ? "ok" : ""} /></div>
    ${estimated ? html`<div class="notice is-warn"><span class="bar"></span><div>对比接口暂不可用，以下参数差异由修复记录推算。</div></div>` : null}
    ${rows.length ? html`<div class="diff-rows"><div class="label">参数对比 · 修复前 / 修复后</div>${rows.map((change) => {
      const max = Math.max(Math.abs(change.before), Math.abs(change.after), 1e-6) * 1.18;
      return html`<div class="diff-row"><div class="diff-param">${change.param}</div><div class="diff-track"><span class="diff-bar before" style=${`width:${bar(change.before, max)}%`}></span><span class="diff-bar after" style=${`width:${bar(change.after, max)}%`}></span><span class="diff-value">${change.before} → ${change.after} <span class=${change.delta < 0 ? "delta-down" : "delta-up"}>(${change.delta > 0 ? "+" : ""}${change.delta})</span></span></div></div>`;
    })}</div>` : null}
    <div class="affected">${resolved.length ? html`<span class="label">已解决</span>` : null}${resolved.map((constraint) => html`<span class="tag is-ok">${constraint}</span>`)}${remaining.length ? html`<span class="label">剩余</span>` : null}${remaining.map((constraint) => html`<span class="tag is-warn">${constraint}</span>`)}</div>
  </div>`;
}