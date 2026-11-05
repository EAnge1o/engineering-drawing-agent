import { useState } from "preact/hooks";
import { html } from "../html.js";
import { BrandMark, Ico } from "../icons.js";
import { StepRail } from "./StepRail.js";

const NAV = [
  { href: "#overview", icon: "grid", text: "任务总览" },
  { href: "#model", icon: "cube", text: "模型与证据" },
  { href: "#issues", icon: "alert", text: "审查问题" },
  { href: "#activity", icon: "bolt", text: "执行记录" },
  { href: "#results", icon: "shield", text: "验证结果" },
];

export function Sidebar({ open, onClose, stage, hasTask, busy, exported, meta }) {
  const [active, setActive] = useState("#overview");
  return html`
    ${open ? html`<button class="sidebar-scrim" aria-label="关闭导航" onClick=${onClose}></button>` : null}
    <aside id="primary-sidebar" class=${`sidebar ${open ? "is-open" : ""}`} aria-label="主导航">
      <div class="sidebar-brand">
        <span class="brand-mark"><${BrandMark} /></span>
        <div><div class="brand-name">Sourth</div><div class="brand-product">工程建模智能体</div></div>
        <button class="icon-btn sidebar-close" aria-label="关闭导航" onClick=${onClose}><${Ico} name="close" /></button>
      </div>
      <div class="nav-section">
        <div class="nav-label">工作区</div>
        <nav class="side-nav">${NAV.map((item) => html`<a href=${item.href} class=${`nav-item ${active === item.href ? "is-current" : ""}`} aria-current=${active === item.href ? "page" : null} onClick=${() => { setActive(item.href); if (onClose) onClose(); }}><${Ico} name=${item.icon} size=${17} /><span>${item.text}</span></a>`)}</nav>
      </div>
      <div class="nav-section workflow-section">
        <div class="nav-label">当前流程</div>
        <${StepRail} stage=${stage} hasTask=${hasTask} busy=${busy} exported=${exported} />
      </div>
      <div class="sidebar-foot">
        <div class="workspace-card"><span class="workspace-avatar">S</span><div><strong>本地工程工作区</strong><span>数据在当前工作区处理</span></div></div>
        <div class="system-line"><span class=${`dot ${meta ? "live" : ""}`}></span>${meta ? "系统能力已检测" : "正在检测系统能力"}</div>
      </div>
    </aside>
  `;
}