const BASE = ''

export async function fetchState() {
  const res = await fetch(`${BASE}/api/state`)
  return res.json()
}

export async function setAct(act: number) {
  const res = await fetch(`${BASE}/api/act/${act}`, { method: 'POST' })
  return res.json()
}

export async function setAttackMode(mode: string) {
  const res = await fetch(`${BASE}/api/attack/${mode}`, { method: 'POST' })
  return res.json()
}

export async function setTenuoMode(mode: string) {
  const res = await fetch(`${BASE}/api/tenuo-mode/${mode}`, { method: 'POST' })
  return res.json()
}

export async function startDemo() {
  const res = await fetch(`${BASE}/api/start`, { method: 'POST' })
  return res.json()
}

export async function resetDemo() {
  const res = await fetch(`${BASE}/api/reset`, { method: 'POST' })
  return res.json()
}

export async function fetchVendors() {
  const res = await fetch(`${BASE}/api/db/vendors`)
  return res.json()
}

export async function fetchPayments() {
  const res = await fetch(`${BASE}/api/db/payments`)
  return res.json()
}

export async function fetchAuthDecisions() {
  const res = await fetch(`${BASE}/api/db/auth-decisions`)
  return res.json()
}

export async function fetchBankChanges() {
  const res = await fetch(`${BASE}/api/db/bank-changes`)
  return res.json()
}

export async function fetchInvoiceAuthSummary() {
  const res = await fetch(`${BASE}/api/db/invoice-auth-summary`)
  return res.json()
}

export async function fetchAgentLogs(agentId?: string) {
  const params = agentId ? `?agent_id=${agentId}` : ''
  const res = await fetch(`${BASE}/api/db/agent-logs${params}`)
  return res.json()
}

export async function fetchWarrantInfo(): Promise<{
  mode: string
  warrant: {
    tools: { name: string; constraints: Record<string, string> }[]
    holder: string | null
    expires_at: string | null
  } | null
  error?: string
}> {
  const res = await fetch(`${BASE}/api/warrant-info`)
  return res.json()
}
