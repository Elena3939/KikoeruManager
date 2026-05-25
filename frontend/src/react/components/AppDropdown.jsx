import * as Select from '@radix-ui/react-select'
import { Check, ChevronDown } from 'lucide-react'
import { cx } from '../utils/format'

export function AppDropdown({
  value,
  onChange,
  options = [],
  placeholder = '请选择',
  className,
  disabled = false,
  width = 160
}) {
  return (
    <Select.Root value={value} onValueChange={onChange} disabled={disabled}>
      <Select.Trigger className={cx('app-dropdown-trigger', className)} style={{ width }} aria-label={placeholder}>
        <Select.Value placeholder={placeholder} />
        <Select.Icon asChild>
          <ChevronDown size={14} strokeWidth={2.3} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="app-dropdown-content" position="popper" sideOffset={8}>
          <Select.Viewport className="app-dropdown-viewport">
            {options.map(option => (
              <Select.Item className="app-dropdown-item" key={option.value} value={option.value}>
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="app-dropdown-check">
                  <Check size={13} strokeWidth={2.5} />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}
