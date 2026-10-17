// Same-origin JSON client for the kit API. No web storage, no absolute URLs.

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

let unauthorizedHandler = null;

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

export async function api(method, path, body) {
  const hasBody = body !== undefined;
  const resp = await fetch(path, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: hasBody ? { 'Content-Type': 'application/json' } : {},
    body: hasBody ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }
  if (!resp.ok) {
    if (resp.status === 401 && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(resp.status, data.error || `Ошибка ${resp.status}`, data);
  }
  return data;
}

// Polls GET /api/jobs/<id> every second until the job leaves 'running'. Returns a cancel function.
export function pollJob(id, onUpdate) {
  let offset = 0;
  let lines = [];
  let stopped = false;
  let timer = null;

  const tick = async () => {
    if (stopped) return;
    try {
      const d = await api('GET', `/api/jobs/${id}?offset=${offset}`);
      offset = d.next_offset;
      lines = lines.concat(d.lines);
      const done = d.status !== 'running';
      onUpdate({ lines, status: d.status, summary: d.summary, resultIp: d.result_ip, done });
      if (done) return;
    } catch (err) {
      onUpdate({ lines, status: 'failed', summary: err.message, resultIp: null, done: true });
      return;
    }
    timer = setTimeout(tick, 1000);
  };

  tick();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
