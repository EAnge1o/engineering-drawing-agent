import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { prefersReducedMotion } from "../store.js";

function fmt(n, decimals) {
  if (!isFinite(n)) return "0";
  return n.toFixed(decimals);
}

/** 指标卡：数值以缓动滚动呈现（reduced-motion 时直接落位）。 */
export function Stat({ label, value, unit, tone, decimals = 0, suffix }) {
  const [shown, setShown] = useState(0);
  // 记录"当前显示值"作为下次动画起点，避免从上一个目标值起跳造成回撤
  const shownRef = useRef(0);

  useEffect(() => {
    const target = Number(value) || 0;
    if (prefersReducedMotion()) {
      shownRef.current = target;
      setShown(target);
      return;
    }
    const from = shownRef.current;
    let raf = 0;
    let start = 0;
    const dur = 640;

    const tick = (t) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = from + (target - from) * eased;
      shownRef.current = v;
      setShown(v);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return html`
    <div class=${`metric ${tone ? `is-${tone}` : ""}`}>
      <div class="metric-label">${label}</div>
      <div class="metric-value">
        ${fmt(shown, decimals)}${suffix || ""}${unit ? html`<span class="metric-unit">${unit}</span>` : null}
      </div>
    </div>
  `;
}