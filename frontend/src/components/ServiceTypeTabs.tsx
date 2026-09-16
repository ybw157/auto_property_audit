import type { ServiceTypeOption } from '../hooks/useServiceTypes'

interface Props {
  options: ServiceTypeOption[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * 服务类型导航：按保安/保洁分类切换查看对应的审核结果。
 *
 * 审核结果页与异常确认页共用，保证两处交互一致。
 * 只有一个可选项时不渲染，避免页面上出现孤零零一个按钮。
 */
export function ServiceTypeTabs({ options, value, onChange, disabled }: Props) {
  if (!options || options.length <= 1) return null
  return (
    <div className="mt-3 inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            disabled={disabled}
            title={opt.hasResult ? (opt.locked ? '已锁定' : '已有审核结果') : '暂无审核结果'}
            onClick={() => onChange(opt.value)}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
              active
                ? 'bg-blue-600 font-medium text-white shadow-sm'
                : 'bg-transparent text-slate-600 hover:bg-white'
            } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
          >
            <span>{opt.label}</span>
            {opt.locked ? (
              <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-white' : 'bg-slate-400'}`} />
            ) : opt.hasResult ? (
              <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-white' : 'bg-blue-500'}`} />
            ) : (
              <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-white/50' : 'bg-slate-300'}`} />
            )}
          </button>
        )
      })}
    </div>
  )
}
