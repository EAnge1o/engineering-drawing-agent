import { render } from "preact";
import { useCallback, useEffect, useState } from "preact/hooks";
import { html } from "./html.js";
import { holeFlagFrom, useStudio } from "./store.js";
import { ToastHost, useToasts } from "./components/Toast.js";
import { TopBar } from "./components/TopBar.js";
import { Sidebar } from "./components/Sidebar.js";
import { DropZone } from "./components/DropZone.js";
import { ViewerPanel } from "./components/ViewerPanel.js";
import { Inspector } from "./components/Inspector.js";
import { IssueList } from "./components/IssueList.js";
import { FixTimeline } from "./components/FixTimeline.js";
import { DiffCompare } from "./components/DiffCompare.js";
import { AgentStatus } from "./components/AgentStatus.js";
import { ReviewQueue } from "./components/ReviewQueue.js";
import { ConfirmDialog } from "./components/ConfirmDialog.js";
import { Stat } from "./components/Stat.js";
import { Ico } from "./icons.js";

const MODES = [{ id: "auto", text: "自动" }, { id: "assisted", text: "辅助" }, { id: "manual", text: "手动" }];
const STAGE_TEXT = ["待开始：请上传图纸或解析内置蓝图。", "图纸解析与确定性审查已完成。", "局部修复与回归验证已完成。", "修复前后对比与证据已就绪。"];

function Panel({ idx, id, title, description, note, actions, children, full, delay }) {
  return html`<section id=${id} class=${`panel ${full ? "panel-full" : ""}`} style=${`--i:${delay || 0}`}>
    <div class="panel-head"><div class="panel-heading"><div class="panel-title">${idx ? html`<span class="idx">${idx}</span>` : null}<span>${title}</span></div>${description ? html`<div class="panel-desc">${description}</div>` : null}</div><div class="panel-actions">${note ? html`<span class="panel-note">${note}</span>` : null}${actions || null}</div></div>
    <div class="panel-body">${children}</div>
  </section>`;
}

function App() {
  const toast = useToasts();
  const s = useStudio(toast);
  const [navOpen, setNavOpen] = useState(false);
  const [confirmFix, setConfirmFix] = useState(false);
  const issues = (s.result && s.result.issues) || (s.task && s.task.issues) || [];
  const closeNav = useCallback(() => setNavOpen(false), []);
  const closeFix = useCallback(() => setConfirmFix(false), []);
  const pageState = s.busy ? "执行中" : s.result ? s.result.state === "DONE" ? "已完成" : "待人工处理" : s.task ? "等待修复" : "待启动";
  const pageTone = s.busy ? "is-running" : s.result ? s.result.state === "DONE" ? "is-done" : "is-warn" : "";

  useEffect(() => {
    const onKey = (event) => {
      const mod = event.ctrlKey || event.metaKey;
      if (event.key === "Escape") setNavOpen(false);
      if (!mod || s.busy || confirmFix) return;
      const target = event.target;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (typing) return;
      if (event.shiftKey && event.key === "Enter") {
        event.preventDefault();
        if (s.task && !s.result) setConfirmFix(true);
      } else if (event.key === "Enter") {
        event.preventDefault();
        s.parseBlueprint();
      } else if (event.key === "s" || event.key === "S") {
        event.preventDefault();
        if (s.result) s.exportReport();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [s.task, s.result, s.busy, s.parseBlueprint, s.exportReport, confirmFix]);

  return html`<div class="app-shell">
    <${Sidebar} open=${navOpen} onClose=${closeNav} stage=${s.stage} hasTask=${!!s.task} busy=${s.busy} exported=${!!s.exportedAt} meta=${s.meta} />
    <div class="app-main">
      <${TopBar} meta=${s.meta} task=${s.task} busy=${s.busy} navOpen=${navOpen} onMenu=${() => setNavOpen(true)} />
      <main class="content">
        <div class="sr-only" role="status" aria-live="polite">${STAGE_TEXT[s.stage]}</div>
        <div class="page-head" id="overview">
          <div><div class="page-eyebrow">AI ENGINEERING WORKSPACE</div><h1 class="page-title">图纸建模工作台</h1><p class="page-description">从工程图纸到可验证的参数化模型。每个解析、修复与回归步骤都有明确依据，高风险决策始终交由人工处理。</p></div>
          <div class="page-actions"><span class=${`status-badge ${pageTone}`}><span class="dot ${s.task ? "live" : ""}"></span>${pageState}</span>${!s.task ? html`<button class="btn btn-primary" disabled=${!!s.busy} onClick=${s.parseBlueprint}><${Ico} name="play" size=${14} />运行示例任务</button>` : !s.result ? html`<button class="btn btn-primary" disabled=${!!s.busy} onClick=${() => setConfirmFix(true)}><${Ico} name="bolt" size=${14} />执行修复</button>` : html`<button class="btn btn-primary" disabled=${!!s.busy} onClick=${s.exportReport}><${Ico} name="download" size=${14} />导出报告</button>`}</div>
        </div>
        ${s.error ? html`<div class="notice is-error" role="alert"><span class="bar"></span><div><strong>操作未完成</strong><div>${s.error}</div></div></div>` : null}
        <div class="summary-grid" aria-label="任务关键指标">
          <${Stat} label="审查问题" value=${issues.length} tone=${issues.length ? "warn" : "ok"} />
          <${Stat} label="成功修复" value=${(s.result && s.result.resolved) || 0} tone="ok" />
          <${Stat} label="预算使用" value=${(s.result && s.result.budget.used) || 0} suffix=${` / ${(s.result && s.result.budget.total) || s.budget}`} tone="accent" />
          <${Stat} label="剩余问题" value=${(s.result && s.result.remaining.length) || 0} tone=${s.result && s.result.remaining.length ? "warn" : "ok"} />
        </div>
        <div class="workspace">
          <div class="work-primary">
            <${Panel} idx="01" title="图纸输入与任务配置" description="支持二维机械零件图，自动解析与人工复核可按需协作" delay=${0}>
              <div class="section-stack"><${DropZone} file=${s.file} onFile=${s.setFile} onInvalid=${(file) => toast.push({ tone: "warn", title: "文件类型不支持", desc: `${file && file.name ? file.name : "该文件"}：请使用 PDF / PNG / JPG` })} />
                <div class="config-grid"><div class="config-block"><span class="config-title">人机协作偏好</span><span class="seg" role="group" aria-label="人机协作偏好">${MODES.map((mode) => html`<button class=${`seg-item ${s.preference === mode.id ? "is-on" : ""}`} aria-pressed=${s.preference === mode.id} onClick=${() => s.setPreference(mode.id)}>${mode.text}</button>`)}</span><div class="config-hint">解析置信度与用户意愿共同决定自动化档位</div></div><label class="field">修复预算<input aria-label="修复预算" type="number" min="1" max="10" value=${s.budget} onInput=${(event) => s.setBudget(Math.min(10, Math.max(1, Math.round(Number(event.target.value) || 1))))} /></label></div>
                <div class="upload-actions"><button class="btn btn-primary" disabled=${!s.file || !!s.busy} onClick=${s.parseDrawing}><${Ico} name="upload" size=${14} />${s.busy === "parse" && s.file ? "解析中…" : "解析上传图纸"}</button><button class="btn" disabled=${!!s.busy} onClick=${s.parseBlueprint}><${Ico} name="doc" size=${14} />使用内置蓝图<span class="kbd">Ctrl ↵</span></button>${s.task && !s.result ? html`<button class="btn btn-accent" disabled=${!!s.busy} onClick=${() => setConfirmFix(true)}><${Ico} name="bolt" size=${14} />${s.busy === "fix" ? "修复中…" : "执行修复"}<span class="kbd">Ctrl ⇧ ↵</span></button>` : null}</div>
              </div>
            <//>
            <${Panel} idx="02" id="model" title="参数化三维模型" description="几何摘要驱动预览，点击审查问题可定位冲突孔" note=${s.geometry ? `内核 ${s.geometry.kernel}` : "等待解析"} delay=${1}>
              <div class="section-stack"><${ViewerPanel} geometry=${s.geometry} highlight=${s.highlight} /><div class="legend"><span class="k"><span class="sw sw-hole"></span>正常孔</span><span class="k"><span class="sw sw-flag"></span>冲突孔</span><span class="k"><span class="sw sw-dim"></span>尺寸标注</span><span class="k"><span class="sw sw-part"></span>零件本体</span></div></div>
            <//>
          </div>
          <div class="work-secondary">
            <${Panel} idx="03" title="Agent 运行状态" description="真实任务阶段与工具执行结果" delay=${1}><${AgentStatus} task=${s.task} result=${s.result} compare=${s.compare} geometry=${s.geometry} busy=${s.busy} exportedAt=${s.exportedAt} explanation=${s.explanation} onExplain=${s.explain} /><//>
            <${Panel} idx="04" title="参数证据" description="来源、置信度与自动化档位" delay=${2}><${Inspector} task=${s.task} meta=${s.meta} /><//>
            <${Panel} idx="05" title="人工处理" description="需要工程判断的事项不会被自动绕过" note=${s.result && s.result.pending_confirmation.length ? `${s.result.pending_confirmation.length} 项待处理` : null} delay=${3}><${ReviewQueue} task=${s.task} result=${s.result} onExport=${s.exportReport} busy=${s.busy} /><//>
          </div>
        </div>
        <div class="lower-panels">
          <${Panel} idx="06" id="issues" title="确定性审查" description="按处理状态筛选问题，并查看规则证据" note=${`${issues.length} 项`} delay=${2}><${IssueList} issues=${issues} remainingIds=${(s.result && s.result.remaining) || null} onSelect=${(issue) => { const flag = holeFlagFrom(issue.constraint_id); if (flag) s.setHighlight([flag]); toast.push({ tone: "ok", title: "已在模型中定位", desc: issue.constraint_id }); }} /><//>
          <${Panel} idx="07" id="activity" title="修复执行记录" description="参数变更、影响集与回归结果全程可追溯" note=${s.result ? `最终状态 ${s.result.state}` : "等待执行"} delay=${3}><${FixTimeline} fixes=${(s.result && s.result.fixes) || []} /><//>
          <${Panel} idx="08" id="results" title="验证结果与参数对比" description="核对修复前后的参数差异和剩余风险" delay=${4} actions=${html`<button class="btn" disabled=${!s.result || !!s.busy} onClick=${s.exportReport}><${Ico} name="download" size=${14} />${s.busy === "export" ? "导出中…" : "导出证据报告"}<span class="kbd">Ctrl S</span></button>`}><${DiffCompare} compare=${s.compare} fallbackResult=${s.result} /><//>
        </div>
        <footer class="statusbar"><span class="k"><span class=${`dot ${s.task ? "live" : ""}`}></span>${s.task ? `任务 ${s.task.task_id} · ${s.result ? s.result.state : "已解析"}` : "工作区空闲"}</span><span class="k">几何内核 ${s.meta ? s.meta.cadquery_available ? "CadQuery" : "摘要模式" : "检测中"}</span><span class="k">模型增强 ${s.meta ? s.meta.llm_available ? "已接入" : "确定性降级" : "检测中"}</span><span class="k push">确定性审查 · 预算硬限制 · 失败回滚</span></footer>
      </main>
    </div>
    <${ConfirmDialog} open=${confirmFix} budget=${s.budget} issueCount=${issues.length} onCancel=${closeFix} onConfirm=${() => { setConfirmFix(false); s.runFix(); }} />
    <${ToastHost} items=${toast.items} dismiss=${toast.dismiss} />
  </div>`;
}

render(html`<${App} />`, document.getElementById("root"));