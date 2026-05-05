async function req<T>(method: string, path: string, body?: object): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Request failed')
  }
  return res.json() as Promise<T>
}

export const api = {
  // Phase 1
  runPhase1: (prompt: string) =>
    req('POST', '/api/phase1/run', { prompt }),
  getPhase1Status: () =>
    req('GET', '/api/phase1/status'),
  submitHITL: (action: 'approve' | 'reject', feedback?: string) =>
    req('POST', '/api/phase1/hitl', { action, feedback: feedback ?? '' }),

  // Phase 2
  runPhase2: () =>
    req('POST', '/api/phase2/run'),
  getPhase2Status: () =>
    req('GET', '/api/phase2/status'),

  // Phase 3
  runPhase3: (dashscope_api_key: string) =>
    req('POST', '/api/phase3/run', { dashscope_api_key }),
  getPhase3Status: () =>
    req('GET', '/api/phase3/status'),

  // Phase 4
  submitEdit: (edit_text: string) =>
    req('POST', '/api/phase4/edit', { edit_text }),
  getHistory: () =>
    req('GET', '/api/phase4/history'),
  revertVersion: (version_id: number) =>
    req('POST', `/api/phase4/revert/${version_id}`),
  getPhase4Status: () =>
    req('GET', '/api/phase4/status'),

  // Outputs
  listOutputs: () =>
    req('GET', '/api/outputs/list'),
  videoUrl: () => '/api/outputs/video',

  // Overall
  getStatus: () =>
    req('GET', '/api/status'),

  // Config (API keys from .env)
  getConfig: () =>
    req('GET', '/api/config'),
}
