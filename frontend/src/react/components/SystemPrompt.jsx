import { useEffect, useState } from 'react'
import { CheckCircle2, CircleHelp, TriangleAlert, X } from 'lucide-react'
import { DotLottieReact } from '@lottiefiles/dotlottie-react'
import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'
import errorAnimation from '../../assets/anime/Error animation.lottie'
import {
  rejectSystemPrompt,
  resolveSystemPrompt,
  systemPromptReasons,
  useSystemPromptState
} from '../stores/systemPromptStore'

function toneIcon(tone) {
  if (tone === 'success') return CheckCircle2
  if (tone === 'warning' || tone === 'danger') return TriangleAlert
  return CircleHelp
}

function toneClass(tone) {
  if (tone === 'success') return 'text-emerald-500'
  if (tone === 'warning') return 'text-amber-500'
  if (tone === 'danger') return 'text-red-500'
  return 'text-blue-500'
}

function buttonClass(tone) {
  if (tone === 'success') return 'km-confirm-success'
  if (tone === 'warning') return 'km-confirm-warning'
  if (tone === 'danger') return 'km-confirm-danger'
  return 'km-confirm-default'
}

export function SystemPromptHost() {
  const { current } = useSystemPromptState()
  const [draft, setDraft] = useState('')
  const [validation, setValidation] = useState('')

  useEffect(() => {
    document.body.classList.toggle('system-prompt-open', Boolean(current))
    setDraft(current?.options?.modelValue || '')
    setValidation('')
    return () => document.body.classList.remove('system-prompt-open')
  }, [current])

  useEffect(() => {
    function handleKeydown(event) {
      if (event.key !== 'Escape' || !current?.options) return
      if (current.options.closeOnPressEscape === false) return
      event.preventDefault()
      rejectSystemPrompt(systemPromptReasons.close)
    }
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [current])

  if (!current) return null

  const options = current.options
  const Icon = toneIcon(options.tone)
  const title = options.title || (options.mode === 'alert' ? '系统提示' : options.mode === 'prompt' ? '请输入' : '确认操作')
  const confirmDisabled = options.confirmLoading || options.confirmDisabled

  function closeByBackdrop() {
    if (options.closeOnClickModal === false) return
    rejectSystemPrompt(systemPromptReasons.close)
  }

  function confirm() {
    if (confirmDisabled) return
    if (options.mode === 'prompt' && options.validator) {
      const result = options.validator(draft)
      if (result !== true && result !== undefined) {
        setValidation(typeof result === 'string' && result.trim() ? result : '输入内容不符合要求')
        return
      }
    }
    resolveSystemPrompt(options.mode === 'prompt' ? draft : true)
  }

  return (
    <Dialog.Root open onOpenChange={open => { if (!open) closeByBackdrop() }}>
      <Dialog.Portal forceMount>
        <AnimatePresence>
          <Dialog.Overlay asChild>
            <motion.div
              className="km-system-prompt"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            />
          </Dialog.Overlay>
          <Dialog.Content asChild>
            <motion.section
              className="km-system-dialog"
              style={{ maxWidth: Math.max(360, Math.min(Number(options.width || 420), 960)) }}
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ type: 'spring', stiffness: 420, damping: 34 }}
            >
              {options.tone === 'success' || options.tone === 'danger' ? (
                <DotLottieReact
                  className="km-system-lottie"
                  src={options.tone === 'success' ? successConfettiAnimation : errorAnimation}
                  autoplay
                  loop={false}
                />
              ) : null}
              <div className="km-system-card">
                <header className="km-system-head">
                  <div>
                    <Icon size={16} className={toneClass(options.tone)} />
                    <Dialog.Title>{title}</Dialog.Title>
                    {options.badge ? <span>{options.badge}</span> : null}
                  </div>
                  {options.showClose ? (
                    <button type="button" aria-label="关闭" onClick={() => rejectSystemPrompt(systemPromptReasons.close)}>
                      <X size={15} />
                    </button>
                  ) : null}
                </header>
                <div className="km-system-body">
                  {options.description ? <p>{options.description}</p> : null}
                  {options.message && options.html ? (
                    <div className="km-system-message" dangerouslySetInnerHTML={{ __html: options.message }} />
                  ) : options.message ? (
                    <div className="km-system-message">{options.message}</div>
                  ) : null}
                  {options.currentValue ? (
                    <div className="km-system-detail">
                      <span>{options.currentLabel || '当前项'}</span>
                      <strong>{options.currentValue}</strong>
                    </div>
                  ) : null}
                  {options.details?.map(detail => (
                    <div className="km-system-detail" key={`${detail.label}-${detail.value}`}>
                      <span>{detail.label || '信息'}</span>
                      <strong>{detail.value || '-'}</strong>
                    </div>
                  ))}
                  {options.mode === 'prompt' ? (
                    <div className="km-system-input">
                      {options.inputType === 'textarea' ? (
                        <textarea value={draft} placeholder={options.placeholder} onChange={event => setDraft(event.target.value)} autoFocus />
                      ) : (
                        <input
                          type={options.inputType === 'password' ? 'password' : 'text'}
                          value={draft}
                          placeholder={options.placeholder}
                          onChange={event => setDraft(event.target.value)}
                          onKeyDown={event => {
                            if (event.key === 'Enter') confirm()
                          }}
                          autoFocus
                        />
                      )}
                      {validation ? <small>{validation}</small> : null}
                    </div>
                  ) : null}
                </div>
                <footer className="km-system-foot">
                  {options.mode !== 'alert' ? (
                    <button type="button" onClick={() => rejectSystemPrompt(systemPromptReasons.cancel)}>
                      {options.cancelText}
                    </button>
                  ) : null}
                  <button type="button" className={buttonClass(options.tone)} disabled={confirmDisabled} onClick={confirm}>
                    {options.confirmLoading ? '处理中...' : options.confirmText}
                  </button>
                </footer>
              </div>
            </motion.section>
          </Dialog.Content>
        </AnimatePresence>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
