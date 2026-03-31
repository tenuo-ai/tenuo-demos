export interface DemoState {
  act: number
  attack_mode: string | null
  auth_stack: string
  tenuo_mode: string  // "local" or "cloud"
  running: boolean
}

export interface AuthDecision {
  layer: string
  allowed: boolean
  reason: string
  latency_us: number
}

export interface ToolCallEvent {
  type: 'tool_call'
  agent_id: string
  tool_name: string
  tool_args: Record<string, unknown>
  result?: string
  timestamp: number
}

export interface AuthDecisionEvent {
  type: 'auth_decision'
  agent_id: string
  tool_name: string
  layer: string
  decision: string
  reason: string
  latency_us: number
  timestamp: number
}

export interface AgentStatusEvent {
  type: 'agent_status'
  agent_id: string
  status: string
  timestamp: number
  [key: string]: unknown
}

export interface DelegationEvent {
  type: 'delegation'
  agent_id: string
  child_id: string
  delegated_tools: string[]
  ttl_minutes: number
  timestamp: number
}

export type DemoEvent =
  | ToolCallEvent
  | AuthDecisionEvent
  | AgentStatusEvent
  | DelegationEvent
  | { type: string; timestamp: number; [key: string]: unknown }

export interface Vendor {
  id: string
  name: string
  bank_account: string
  bank_routing: string
  verified: boolean
}

export interface Payment {
  id: string
  invoice_id: string
  vendor_id: string
  vendor_name: string
  amount: number
  bank_account: string
  bank_routing: string
  status: string
  created_at: string
}

export interface AgentLog {
  id: number
  run_id: string
  agent_id: string
  event_type: 'thinking' | 'tool_call' | 'tool_result' | 'delegation' | 'status' | 'tenuo_block'
  content: string | null
  tool_name: string | null
  tool_args: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface BankChange {
  id: number
  vendor_id: string
  old_account: string
  new_account: string
  old_routing: string
  new_routing: string
  changed_by: string
  reason: string
  created_at: string
}
