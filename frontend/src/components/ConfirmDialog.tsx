import { useEffect } from 'react'

interface ConfirmDialogProps {
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel }: ConfirmDialogProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-6"
      onMouseDown={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        className="rise w-90 rounded-card border border-line bg-card p-7 shadow-bloom"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="font-display text-lg text-ink">{title}</div>
        <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
        <div className="mt-6 flex justify-end gap-2.5">
          <button
            onClick={onCancel}
            className="min-h-10 cursor-pointer rounded-pill border border-line-strong bg-transparent px-4 py-2 font-sans text-[13px] font-medium text-ink hover:border-pine hover:text-pine"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="min-h-10 cursor-pointer rounded-pill border-none bg-error px-4 py-2 font-sans text-[13px] font-semibold text-on-pine"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
