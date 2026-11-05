import { html } from "../html.js";
import { Ico } from "../icons.js";

function Chip({ on, warn, children }) {
  const cls = `chip ${on ? "on" : warn ? "warn" : "off"}`;
  return html`<span class=${cls}><span class="led"></span>${children}</span>`;
}

export function TopBar({ meta, task, busy, onMenu, navOpen }) {
  const cad = meta ? meta.cadquery_available : null;
  const llm = meta ? meta.llm_available : null;
  return html`
    <header class="topbar">
      <div class="topbar-context">
        <button class="icon-btn mobile-menu" aria-label="打开导航" aria-controls="primary-sidebar" aria-expanded=${!!navOpen} onClick=${onMenu}><${Ico} name="menu" /></button>
        <div>
          <div class="breadcrumb">工程图纸建模与自纠错 Agent <span>/</span> 工作台</div>
          <div class="topbar-title">任务工作台</div>
        </div>
      </div>
      <div class="chips" role="status" aria-live="off">
        ${busy ? html`<span class="chip on"><span class="spinner"></span>任务执行中</span>` : null}
        <${Chip} on=${cad === true} warn=${cad === false}><${Ico} name="cube" size=${13} />几何内核 ${cad == null ? "…" : cad ? "就绪" : "摘要模式"}<//>
        <${Chip} on=${llm === true}><${Ico} name="spark" size=${13} />模型增强 ${llm == null ? "…" : llm ? "已接入" : "确定性"}<//>
        ${task ? html`<${Chip} on><${Ico} name="doc" size=${13} />任务 ${task.task_id}<//>` : null}
      </div>
    </header>
  `;
}