import { SUBJECT_NAMES_CN } from '../config/moduleRouting'

export default function SubjectFilter({ value, onChange, includeAll = false, name = 'subject', disabled = false }) {
  const options = [
    ...(includeAll ? [['', '全部']] : []),
    ...Object.entries(SUBJECT_NAMES_CN),
  ]

  return (
    <div className="filter-row">
      <span className="filter-label" id={name + '-label'}>学科</span>
      <div className="filter-options" role="radiogroup" aria-labelledby={name + '-label'}>
        {options.map(([key, label]) => (
          <label key={key} className={'filter-option' + (value === key ? ' is-selected' : '')}>
            <input type="radio" name={name} value={key} checked={value === key} disabled={disabled} onChange={() => onChange(key)} />
            {label}
          </label>
        ))}
      </div>
    </div>
  )
}
