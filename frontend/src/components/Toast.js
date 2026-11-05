import { useCallback, useMemo, useState } from "preact/hooks";
import { html } from "../html.js";
import { Ico } from "../icons.js";

/** Toast 控制器：自动消失，支持手动关闭。 */
export function useToasts() {
  const [items, setItems] = useState([]);

  const dismiss = useCallback((id) => {
    setItems((cur) => cur.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((t) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const duration = t.duration || 4200;
    setItems((cur) => [...cur.slice(-3), { id, tone: "ok", ...t }]);
    window.setTimeout(() => dismiss(id), duration);
  }, [dismiss]);

  // 稳定引用：避免每次渲染重建对象导致下游 effect 重绑
  return useMemo(() => ({ items, push, dismiss }), [items, push, dismiss]);
}

const ICON_BY_TONE = { ok: "check", warn: "alert", err: "alert" };

export function ToastHost({ items, dismiss }) {
  if (!items.length) return null;
  return html`
    <div class="toast-host" role="region" aria-live="polite" aria-label="通知">
      ${items.map(
        (t) => html`
          <div class=${`toast ${t.tone}`} role="status">
            <span class="ico"><${Ico} name=${ICON_BY_TONE[t.tone] || "spark"} /></span>
            <div class="toast-body">
              <div class="toast-title">${t.title}</div>
              ${t.desc ? html`<div class="toast-desc">${t.desc}</div>` : null}
            </div>
            <button class="icon-btn" title="关闭" aria-label="关闭通知" onClick=${() => dismiss(t.id)}>
              <${Ico} name="close" size=${13} />
            </button>
          </div>
        `
      )}
    </div>
  `;
}