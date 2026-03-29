/**
 * Invoice inspector panel — shows the invoice data the agent receives,
 * including the injection payload in the notes field.
 *
 * This lets the presenter say: "Look at this invoice. Looks normal, right?
 * Now look at the notes field..."
 */
import { useEffect, useState } from 'react'

interface Invoice {
  id: string
  vendor_id: string
  vendor_name: string
  po_id: string
  department: string
  amount: number
  currency: string
  description: string
  notes: string | null
  status: string
  due_date: string | null
}

export function InvoiceInspector({ attackEnabled }: { attackEnabled: boolean }) {
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [selected, setSelected] = useState<string>('INV-2024-1847')

  useEffect(() => {
    const fetchInvoices = async () => {
      try {
        // Fetch from vendor portal (which has injection payloads when enabled)
        const ids = ['INV-2024-1841', 'INV-2024-1847', 'INV-2024-1843']
        const results = await Promise.all(
          ids.map(async (id) => {
            const res = await fetch(`/api/portal/invoice/${id}`)
            return res.json()
          })
        )
        setInvoices(results.filter((r) => !r.error))
      } catch {
        // ignore
      }
    }
    fetchInvoices()
  }, [attackEnabled])

  const invoice = invoices.find((i) => i.id === selected)

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
          Invoice Inspector
        </h2>
        <div className="flex gap-1">
          {['INV-2024-1841', 'INV-2024-1847', 'INV-2024-1843'].map((id) => (
            <button
              key={id}
              onClick={() => setSelected(id)}
              className={`px-2 py-0.5 text-xs rounded ${
                selected === id
                  ? id === 'INV-2024-1847'
                    ? 'bg-red-600 text-white'
                    : 'bg-gray-600 text-white'
                  : 'bg-gray-800 text-gray-500 hover:bg-gray-700'
              }`}
            >
              {id.replace('INV-2024-', '')}
            </button>
          ))}
        </div>
      </div>

      {invoice ? (
        <div className="space-y-3">
          {/* Invoice header */}
          <div className="bg-gray-900 border border-gray-800 rounded p-3">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-gray-600">Invoice:</span>{' '}
                <span className="text-gray-200">{invoice.id}</span>
              </div>
              <div>
                <span className="text-gray-600">Vendor:</span>{' '}
                <span className="text-gray-200">{invoice.vendor_name}</span>
                <span className="text-gray-600 ml-1">({invoice.vendor_id})</span>
              </div>
              <div>
                <span className="text-gray-600">Amount:</span>{' '}
                <span className="text-white font-medium">
                  ${invoice.amount.toLocaleString()} {invoice.currency}
                </span>
              </div>
              <div>
                <span className="text-gray-600">PO:</span>{' '}
                <span className="text-gray-200">{invoice.po_id}</span>
              </div>
              <div className="col-span-2">
                <span className="text-gray-600">Description:</span>{' '}
                <span className="text-gray-300">{invoice.description}</span>
              </div>
            </div>
          </div>

          {/* Notes field — this is where the injection lives */}
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-gray-500">Notes field</span>
              {invoice.notes && invoice.id === 'INV-2024-1847' && attackEnabled && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/50 text-red-400 border border-red-800">
                  Contains injection payload
                </span>
              )}
            </div>
            <div
              className={`text-xs p-3 rounded border font-mono whitespace-pre-wrap ${
                invoice.notes && invoice.id === 'INV-2024-1847' && attackEnabled
                  ? 'bg-red-950/30 border-red-800 text-red-300'
                  : 'bg-gray-900 border-gray-800 text-gray-400'
              }`}
            >
              {invoice.notes || <span className="text-gray-600 italic">No notes</span>}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-gray-600 text-sm">Loading invoices...</div>
      )}
    </div>
  )
}
