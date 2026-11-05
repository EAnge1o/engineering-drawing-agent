import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { api } from "./api.js";

export function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function holeFlagFrom(constraintId) {
  const m = (constraintId || "").match(/^c_h(\d+)_inside$/);
  return m ? `hole_h${m[1]}` : null;
}

export function useStudio(toast) {
  const [preference, setPreference] = useState("auto");
  const [budget, setBudget] = useState(5);
  const [file, setFile] = useState(null);
  const [task, setTask] = useState(null);
  const [result, setResult] = useState(null);
  const [compare, setCompare] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [meta, setMeta] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [highlight, setHighlight] = useState([]);
  const [explanation, setExplanation] = useState(null);
  const [exportedAt, setExportedAt] = useState(null);
  const seqRef = useRef(0);

  useEffect(() => { api.getMeta().then(setMeta).catch(() => setMeta(null)); }, []);

  const reset = useCallback(() => {
    setResult(null);
    setCompare(null);
    setError(null);
    setHighlight([]);
    setExplanation(null);
    setExportedAt(null);
  }, []);

  const applyTask = useCallback(async (resp, source) => {
    setTask({ ...resp, source, parse: resp.parse || null });
    try { setGeometry(await api.getModel(resp.task_id)); } catch { setGeometry(null); }
    setHighlight((resp.issues || []).map((i) => holeFlagFrom(i.constraint_id)).filter(Boolean));
  }, []);

  const parseBlueprint = useCallback(async () => {
    const seq = ++seqRef.current;
    setBusy("parse");
    reset();
    try {
      const resp = await api.createTask({ preference, budget });
      if (seq !== seqRef.current) return;
      await applyTask(resp, "blueprint");
      toast.push({ tone: "ok", title: "图纸已解析", desc: `预算 ${budget} 步 · 模式 ${preference}` });
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(String(e));
      toast.push({ tone: "err", title: "解析失败", desc: String(e) });
    } finally { if (seq === seqRef.current) setBusy(null); }
  }, [preference, budget, applyTask, reset, toast]);

  const parseDrawing = useCallback(async () => {
    if (!file) return;
    const seq = ++seqRef.current;
    setBusy("parse");
    reset();
    try {
      const resp = await api.createFromDrawing(file, { preference, budget });
      if (seq !== seqRef.current) return;
      await applyTask(resp, "drawing");
      toast.push({ tone: "ok", title: "图纸文件已解析", desc: file.name });
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(String(e));
      toast.push({ tone: "err", title: "图纸解析失败", desc: String(e) });
    } finally { if (seq === seqRef.current) setBusy(null); }
  }, [file, preference, budget, applyTask, reset, toast]);

  const runFix = useCallback(async () => {
    if (!task || busy) return;
    setBusy("fix");
    setError(null);
    setExplanation(null);
    setExportedAt(null);
    try {
      const r = await api.fix(task.task_id, { budget, mode: "A1" });
      setResult(r);
      try { setGeometry(await api.getModel(task.task_id)); } catch {}
      try { setCompare(await api.compare(task.task_id)); } catch { setCompare(null); }
      const ok = r.state === "DONE";
      toast.push({ tone: ok ? "ok" : "warn", title: ok ? "修复闭环完成" : "部分问题待人工确认", desc: ok ? `成功修复 ${r.resolved} 处 · 预算 ${r.budget.used}/${r.budget.total}` : `剩余 ${r.remaining.length} 项 · 待确认 ${r.pending_confirmation.length} 项` });
    } catch (e) {
      setError(String(e));
      toast.push({ tone: "err", title: "修复失败", desc: String(e) });
    } finally { setBusy(null); }
  }, [task, budget, busy, toast]);

  const exportReport = useCallback(async () => {
    if (!task || busy) return;
    setBusy("export");
    try {
      const [report, evidence] = await Promise.all([api.getReport(task.task_id), api.evidence(task.task_id).catch(() => null)]);
      const payload = evidence ? { ...report, evidence } : report;
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${task.task_id}-report.json`;
      a.click();
      URL.revokeObjectURL(url);
      setExportedAt(new Date().toISOString());
      toast.push({ tone: "ok", title: "报告已导出", desc: evidence && evidence.verification ? `证据包校验：${evidence.verification.all_ok ? "通过" : "失败"}` : "含审查与修复记录" });
    } catch (e) { toast.push({ tone: "err", title: "导出失败", desc: String(e) }); }
    finally { setBusy(null); }
  }, [task, busy, toast]);

  const explain = useCallback(async () => {
    if (!task || !result || busy) return null;
    setBusy("explain");
    try {
      const value = await api.explain(task.task_id);
      setExplanation(value);
      toast.push({ tone: "ok", title: "任务说明已生成", desc: value.source === "llm" ? "由已配置模型生成" : "由确定性结果生成" });
      return value;
    } catch (e) {
      toast.push({ tone: "err", title: "说明生成失败", desc: String(e) });
      return null;
    } finally { setBusy(null); }
  }, [task, result, busy, toast]);

  const stage = compare ? 3 : result ? 2 : task ? 1 : 0;
  return { preference, setPreference, budget, setBudget, file, setFile, task, result, compare, geometry, meta, busy, error, highlight, setHighlight, explanation, exportedAt, stage, parseBlueprint, parseDrawing, runFix, exportReport, explain };
}