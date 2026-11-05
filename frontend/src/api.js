const BASE = "/api";

async function responseError(res) {
  const raw = await res.text();
  try {
    const data = JSON.parse(raw);
    const detail = typeof data.detail === "string" ? data.detail : data.message;
    return new Error(detail ? `${detail}（HTTP ${res.status}）` : `请求未完成（HTTP ${res.status}）`);
  } catch {
    return new Error(raw && !raw.trim().startsWith("<") ? `${raw}（HTTP ${res.status}）` : `服务暂时不可用（HTTP ${res.status}）`);
  }
}

async function req(path, init) {
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...(init || {}) });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

function post(path, body) {
  return req(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

export const api = {
  getMeta: () => req("/meta"),
  createTask: (body) => post("/tasks", body),
  getTask: (tid) => req(`/tasks/${tid}`),
  getIssues: (tid) => req(`/tasks/${tid}/issues`),
  getModel: (tid) => req(`/tasks/${tid}/model`),
  fix: (tid, body) => post(`/tasks/${tid}/fix`, body),
  getReport: (tid) => req(`/tasks/${tid}/report`),
  compare: (tid) => req(`/tasks/${tid}/compare`),
  explain: (tid) => post(`/tasks/${tid}/explain`),
  evidence: (tid) => post(`/tasks/${tid}/evidence`),
  createFromDrawing: async (file, opts) => {
    const form = new FormData();
    form.append("file", file);
    form.append("preference", (opts && opts.preference) || "auto");
    form.append("budget", String((opts && opts.budget) != null ? opts.budget : 5));
    form.append("auto_threshold", String((opts && opts.auto_threshold) != null ? opts.auto_threshold : 0.55));
    const res = await fetch(`${BASE}/tasks/from-drawing`, { method: "POST", body: form });
    if (!res.ok) throw await responseError(res);
    return res.json();
  },
};