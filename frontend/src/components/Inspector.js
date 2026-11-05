import { html } from "../html.js";
import { Ico } from "../icons.js";

const MODE_LABEL = { A0: "A0 全自动", A1: "A1 辅助", A2: "A2 手动" };
const SOURCE_LABEL = { drawing: "图纸", user: "人工", inferred: "推断", blueprint: "蓝图" };

function confClass(value) {
  if (value < 0.55) return "is-crit";
  if (value < 0.85) return "is-low";
  return "";
}

export function Inspector({ task, meta }) {
  if (!task) {
    return html`<div class="empty"><span class="empty-icon"><${Ico} name="doc" size=${19} /></span><div class="empty-title">等待参数证据</div><div class="empty-desc">解析后将逐项列出尺寸来源、置信度与自动化档位，便于人工复核。</div></div>`;
  }
  const parse = task.parse || {};
  const fields = parse.fields || [];
  return html`<div class="section-stack">
    <div class="toolbar"><span class=${`badge mode-${parse.overall_mode}`}>${MODE_LABEL[parse.overall_mode] || parse.overall_mode}</span>${(parse.pending || []).length ? html`<span class="badge sev-medium">待确认 ${parse.pending.length}</span>` : null}<span class="badge">${task.source_file ? `来源 ${task.source_file}` : "结构化蓝图"}</span></div>
    ${(parse.notes || []).length ? html`<div class="notice is-warn"><span class="bar"></span><div>${parse.notes.map((note) => html`<div>${note}</div>`)}</div></div>` : null}
    ${fields.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>参数</th><th class="num">值</th><th>置信度</th><th>状态</th><th>来源</th><th>档位</th></tr></thead><tbody>${fields.map((field) => html`<tr>
      <td class="col-param mono">${field.id}</td><td class="num">${field.value}</td>
      <td><span class="conf-bar"><span class="conf-track" aria-hidden="true"><span class=${`conf-fill ${confClass(field.confidence)}`} style=${`width:${Math.round((field.confidence || 0) * 100)}%`}></span></span><span class="mono">${(field.confidence || 0).toFixed(2)}</span></span></td>
      <td><span class=${`badge ${field.needs_confirm ? "sev-medium" : ""}`}>${field.needs_confirm ? "需确认" : field.status}</span></td><td>${SOURCE_LABEL[field.source] || field.source || "—"}</td><td><span class=${`badge mode-${field.mode}`}>${field.mode}</span></td>
    </tr>`)}</tbody></table></div>` : html`<div class="empty"><div class="empty-title">没有可展示的结构化字段</div><div class="empty-desc">请补充图纸标注或使用人工录入模式。</div></div>`}
    ${meta && meta.thresholds ? html`<div class="muted mono">自动判定阈值：高 ${meta.thresholds.high} · 低 ${meta.thresholds.low}</div>` : null}
  </div>`;
}