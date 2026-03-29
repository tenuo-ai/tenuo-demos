import { useEffect, useState } from 'react'
import { fetchVendors, fetchPayments, fetchBankChanges } from '../lib/api'
import type { Vendor, Payment, BankChange } from '../lib/types'

// The attacker's bank details — highlight if these appear
const ATTACKER_ACCOUNT = '8847291034'
const ATTACKER_ROUTING = '071000013'

export function DatabaseState() {
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [payments, setPayments] = useState<Payment[]>([])
  const [bankChanges, setBankChanges] = useState<BankChange[]>([])

  useEffect(() => {
    const poll = async () => {
      try {
        setVendors(await fetchVendors())
        setPayments(await fetchPayments())
        setBankChanges(await fetchBankChanges())
      } catch {
        // ignore
      }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  // Only show key vendors for demo clarity
  const keyVendors = vendors.filter((v) =>
    ['V-4521', 'V-4522', 'V-4523'].includes(v.id)
  )

  return (
    <div className="p-4 space-y-4">
      {/* Vendor Bank Details */}
      <div>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-2">
          Vendor Bank Details
        </h2>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="py-1 text-left">Vendor</th>
              <th className="py-1 text-left">Account</th>
              <th className="py-1 text-left">Routing</th>
            </tr>
          </thead>
          <tbody>
            {keyVendors.map((v) => {
              const isCompromised =
                v.bank_account === ATTACKER_ACCOUNT &&
                v.bank_routing === ATTACKER_ROUTING

              return (
                <tr
                  key={v.id}
                  className={
                    isCompromised
                      ? 'bg-red-950/50 animate-pulse'
                      : 'border-b border-gray-900'
                  }
                >
                  <td className="py-1">
                    <span className="text-gray-500">{v.id}</span>{' '}
                    <span className={isCompromised ? 'text-red-400' : ''}>{v.name}</span>
                  </td>
                  <td className={`py-1 font-mono ${isCompromised ? 'text-red-400 font-bold' : 'text-gray-300'}`}>
                    {v.bank_account}
                  </td>
                  <td className={`py-1 font-mono ${isCompromised ? 'text-red-400 font-bold' : 'text-gray-300'}`}>
                    {v.bank_routing}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Bank Change Audit */}
      {bankChanges.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-red-400 uppercase tracking-wider mb-2">
            Bank Changes Detected
          </h2>
          {bankChanges.map((c) => (
            <div key={c.id} className="text-xs p-2 bg-red-950/30 rounded border border-red-900 mb-1">
              <div>
                <span className="text-gray-500">{c.vendor_id}</span>
                {' → '}
                <span className="text-red-400">{c.new_account}</span>
                {' / '}
                <span className="text-red-400">{c.new_routing}</span>
              </div>
              <div className="text-gray-600 mt-1">
                Changed by: {c.changed_by} | Reason: {c.reason?.slice(0, 60)}...
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Recent Payments */}
      {payments.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-2">
            Recent Payments
          </h2>
          <div className="space-y-1">
            {payments.slice(0, 5).map((p) => {
              const toAttacker =
                p.bank_account === ATTACKER_ACCOUNT &&
                p.bank_routing === ATTACKER_ROUTING

              return (
                <div
                  key={p.id}
                  className={`text-xs p-2 rounded ${
                    toAttacker
                      ? 'bg-red-950/50 border border-red-800'
                      : 'bg-gray-900 border border-gray-800'
                  }`}
                >
                  <span className="text-gray-500">{p.id}</span>
                  {' → '}
                  <span className={toAttacker ? 'text-red-400' : 'text-gray-300'}>
                    {p.vendor_name}
                  </span>
                  {' $'}
                  <span className="text-white">{p.amount.toLocaleString()}</span>
                  {toAttacker && (
                    <span className="ml-2 text-red-500 font-medium">
                      ⚠ SENT TO ATTACKER ACCOUNT
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
