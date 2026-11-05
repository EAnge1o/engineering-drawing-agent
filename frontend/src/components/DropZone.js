import { useCallback, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { Ico } from "../icons.js";

const ALLOWED = [".pdf", ".png", ".jpg", ".jpeg", ".bmp"];

export function DropZone({ file, onFile, onInvalid }) {
  const [over, setOver] = useState(false);
  const inputRef = useRef(null);

  const pick = useCallback((f) => {
    if (!f) return;
    const name = (f.name || "").toLowerCase();
    if (!ALLOWED.some((ext) => name.endsWith(ext))) {
      if (onInvalid) onInvalid(f);
      return;
    }
    onFile(f);
  }, [onFile, onInvalid]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    pick(f);
  }, [pick]);

  const onDragOver = useCallback((e) => {
    e.preventDefault();
    setOver(true);
  }, []);

  const onDragLeave = useCallback(() => setOver(false), []);

  const onKey = useCallback((e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (inputRef.current) inputRef.current.click();
    }
  }, []);

  return html`
    <div
      class=${`dropzone ${over ? "is-over" : ""}`}
      role="button"
      tabindex="0"
      aria-label="上传工程图纸，支持 PDF、PNG、JPG"
      onClick=${() => inputRef.current && inputRef.current.click()}
      onKeyDown=${onKey}
      onDrop=${onDrop}
      onDragOver=${onDragOver}
      onDragLeave=${onDragLeave}
    >
      <${Ico} name="upload" size=${30} cls=${"dz-icon"} />
      <div class="dz-title">${file ? file.name : "拖放或点击上传工程图纸"}</div>
      <div class="dz-hint">支持矢量 PDF（推荐）与 PNG / JPG · 单视图机械零件图</div>
      <input
        ref=${inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.bmp"
        onChange=${(e) => pick(e.target.files && e.target.files[0])}
      />
    </div>
  `;
}