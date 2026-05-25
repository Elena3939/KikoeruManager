import { Loader2, X } from 'lucide-react'
import { Slot } from '@radix-ui/react-slot'
import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { cx } from '../utils/format'

export function Button({ variant = 'ghost', size = 'md', className, children, loading, asChild = false, ...props }) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      type={asChild ? undefined : 'button'}
      className={cx('km-button', `km-button--${variant}`, `km-button--${size}`, className)}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? <Loader2 size={16} className="km-spin" /> : null}
      {children}
    </Comp>
  )
}

export function IconButton({ title, className, children, ...props }) {
  return (
    <button type="button" className={cx('km-icon-button', className)} title={title} aria-label={title} {...props}>
      {children}
    </button>
  )
}

export function Card({ className, children }) {
  return <section className={cx('km-card', className)}>{children}</section>
}

export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="km-page-header">
      <div>
        {eyebrow ? <div className="km-eyebrow">{eyebrow}</div> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="km-page-actions">{actions}</div> : null}
    </header>
  )
}

export function Field({ label, children, hint }) {
  return (
    <label className="km-field">
      <span>{label}</span>
      {children}
      {hint ? <small>{hint}</small> : null}
    </label>
  )
}

export function TextInput(props) {
  return <input className={cx('km-input', props.className)} {...props} />
}

export function TextArea(props) {
  return <textarea className={cx('km-input km-textarea', props.className)} {...props} />
}

export function SelectInput({ children, ...props }) {
  return (
    <select className={cx('km-input', props.className)} {...props}>
      {children}
    </select>
  )
}

export function EmptyState({ icon: Icon, title = '暂无数据', description }) {
  return (
    <div className="km-empty">
      {Icon ? <Icon size={32} strokeWidth={1.7} /> : null}
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
    </div>
  )
}

export function LoadingState({ label = '加载中...' }) {
  return (
    <div className="km-loading">
      <Loader2 size={22} className="km-spin" />
      <span>{label}</span>
    </div>
  )
}

export function Modal({ title, width = 720, children, footer, onClose }) {
  return (
    <Dialog.Root open onOpenChange={open => { if (!open) onClose?.() }}>
      <Dialog.Portal forceMount>
        <AnimatePresence>
          <Dialog.Overlay asChild>
            <motion.div
              className="km-modal-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            />
          </Dialog.Overlay>
          <Dialog.Content asChild>
            <motion.section
              className="km-modal"
              style={{ maxWidth: width }}
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ type: 'spring', stiffness: 420, damping: 34 }}
            >
              <header className="km-modal-head">
                <Dialog.Title>{title}</Dialog.Title>
                <Dialog.Close asChild>
                  <IconButton title="关闭">
                    <X size={16} />
                  </IconButton>
                </Dialog.Close>
              </header>
              <div className="km-modal-body">{children}</div>
              {footer ? <footer className="km-modal-foot">{footer}</footer> : null}
            </motion.section>
          </Dialog.Content>
        </AnimatePresence>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
