import { useEffect, useRef } from "preact/hooks";
import { html } from "../html.js";
import { Ico } from "../icons.js";

export function ConfirmDialog({ open, budget, issueCount, onCancel, onConfirm }) {
  const confirmRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    if (confirmRef.current) confirmRef.current.focus();
    const onKey = (event) => {
      if (event.key === "Escape") onCancel();
      if (event.key === "Tab") {
        const nodes = document.querySelectorAll(".dialog button:not(:disabled)");
        if (!nodes.length) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous && previous.focus) previous.focus();
    };
  }, [open, onCancel]);
  if (!open) return null;
  return html`<div class="dialog-backdrop" onMouseDown=${(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="fix-dialog-title" aria-describedby="fix-dialog-desc">
      <div class="dialog-head"><div><h2 class="dialog-title" id="fix-dialog-title">确认执行自动修复</h2><p class="dialog-subtitle">Agent 将在硬预算内修改参数并执行回归验证</p></div><button class="icon-btn" aria-label="关闭确认弹窗" onClick=${onCancel}><${Ico} name="close" /></button></div>
      <div class="dialog-body"><p id="fix-dialog-desc">本次操作仅处理可修复问题。高风险或低置信度事项会停止并转入人工处理，不会强制通过。</p>
        <div class="dialog-facts"><div class="dialog-fact"><span>待审查问题</span><strong>${issueCount} 项</strong></div><div class="dialog-fact"><span>修复预算</span><strong>${budget} 步</strong></div><div class="dialog-fact"><span>协作模式</span><strong>A1 辅助</strong></div></div>
        <div class="notice is-warn"><span class="bar"></span><div>失败修复将自动回滚。执行完成后请核对参数变更和回归结果。</div></div>
      </div>
      <div class="dialog-actions"><button class="btn" onClick=${onCancel}>取消</button><button ref=${confirmRef} class="btn btn-primary" onClick=${onConfirm}><${Ico} name="bolt" size=${14} />确认并执行</button></div>
    </section>
  </div>`;
}