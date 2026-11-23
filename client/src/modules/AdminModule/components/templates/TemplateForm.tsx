import type {FormEvent} from 'react';
import type {TemplateElement, TemplateFieldOut, TemplateIn} from '~/models/api';

export const templateKinds: Record<TemplateIn['kind'], string> = {
    front: 'Лицевая сторона', back: 'Оборотная сторона',
    changed: 'Лицевая для изменённых данных', changed_back: 'Оборотная для изменённых данных',
};

const elementTypes: Record<TemplateElement['type'], string> = {field: 'Поле', text: 'Текст', qr: 'QR'};
const geometry = [
    ['x_mm', 'Слева, мм', 0], ['y_mm', 'Сверху, мм', 0],
    ['w_mm', 'Ширина элемента, мм', 0.01], ['h_mm', 'Высота элемента, мм', 0.01],
] as const;
const typography = [
    ['font_size', 'Кегль, pt', 0.01, 0.01], ['min_font_size', 'Мин. кегль, pt', 0.01, 0.01],
    ['max_lines', 'Макс. строк', 1, 1],
] as const;

function NumberField({label, value, min, max, step = 0.01, onChange}: {
    label: string; value: number; min: number; max?: number; step?: number;
    onChange: (value: number) => void;
}) {
    return <label>{label}<input className="input" type="number" required min={min} max={max} step={step}
        value={Number.isFinite(value) ? value : ''} onChange={e => onChange(e.target.valueAsNumber)}/></label>;
}

export function TemplateForm({draft, fields, busy, bound, onChange, onSave}: {
    draft: TemplateIn; fields: TemplateFieldOut[]; busy: boolean; bound: boolean;
    onChange: (draft: TemplateIn) => void; onSave: () => void;
}) {
    const elements = draft.elements ?? [];
    const participantFields = fields.filter(field => field.key !== 'text' && field.key !== 'qr');
    const defaultField = participantFields.find(field => field.key === 'full_name')?.key ?? participantFields[0]?.key;
    function editElement(index: number, patch: Partial<TemplateElement>) {
        onChange({...draft, elements: elements.map((element, i) => i === index ? {...element, ...patch} : element)});
    }
    function addElement() {
        onChange({...draft, elements: [...elements, {
            type: 'field', field: defaultField ?? '', x_mm: 0, y_mm: 0,
            w_mm: Math.min(draft.width_mm || 20, 20), h_mm: Math.min(draft.height_mm || 10, 10),
            font_size: 14, min_font_size: 8, max_lines: 1, bold: false, align: 'left',
        }]});
    }
    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        onSave();
    }

    return <form onSubmit={submit}>
        <fieldset disabled={busy} className="template_fields">
            <legend>Параметры шаблона</legend>
            <div className="template_grid">
                <label>Название<input className="input" value={draft.name} required maxLength={100}
                    onChange={e => onChange({...draft, name: e.target.value})}/></label>
                <label>Сторона<select aria-label="Сторона" className="input" value={draft.kind} disabled={bound}
                    onChange={e => onChange({...draft, kind: e.target.value as TemplateIn['kind']})}>
                    {Object.entries(templateKinds).map(([kind, title]) => <option key={kind} value={kind}>{title}</option>)}
                </select></label>
                <NumberField label="Ширина ленты, мм" value={draft.width_mm} min={0.01} max={200}
                    onChange={width_mm => onChange({...draft, width_mm})}/>
                <NumberField label="Высота наклейки, мм" value={draft.height_mm} min={0.01} max={200}
                    onChange={height_mm => onChange({...draft, height_mm})}/>
                <NumberField label="Зазор, мм" value={draft.gap_mm ?? 2} min={0} max={20}
                    onChange={gap_mm => onChange({...draft, gap_mm})}/>
            </div>
            {elements.map((element, i) => <fieldset key={i} className="template_fields">
                <legend>Элемент {i + 1}</legend>
                <div className="template_grid">
                    <label>Тип элемента<select className="input" value={element.type} onChange={e => {
                        const type = e.target.value as TemplateElement['type'];
                        editElement(i, {type, field: type === 'field' ? element.field || defaultField : null,
                            text: type === 'text' ? element.text : null});
                    }}>
                        {Object.entries(elementTypes).map(([type, label]) => <option key={type} value={type}>{label}</option>)}
                    </select></label>
                    {element.type === 'field' && <label>Поле участника<select className="input" required
                        value={element.field ?? ''} onChange={e => editElement(i, {field: e.target.value})}>
                        <option value="">Выберите поле</option>
                        {element.field && !participantFields.some(field => field.key === element.field) &&
                            <option value={element.field}>{element.field}</option>}
                        {participantFields.map(field => <option key={field.key} value={field.key}>{field.label}</option>)}
                    </select></label>}
                    {element.type === 'text' && <label>Надпись<input className="input" required maxLength={500}
                        value={element.text ?? ''} onChange={e => editElement(i, {text: e.target.value})}/></label>}
                    {geometry.map(([key, label, min]) => <NumberField key={key} label={label} value={element[key]} min={min}
                        onChange={value => editElement(i, {[key]: value})}/>)}
                    {element.type !== 'qr' && typography.map(([key, label, min, step]) =>
                        <NumberField key={key} label={label} value={element[key]} min={min} step={step}
                            onChange={value => editElement(i, {[key]: value})}/>)}
                    {element.type !== 'qr' && <label>Выравнивание<select className="input" value={element.align}
                        onChange={e => editElement(i, {align: e.target.value as TemplateElement['align']})}>
                        <option value="left">Слева</option><option value="center">По центру</option>
                        <option value="right">Справа</option>
                    </select></label>}
                </div>
                <div className="template_actions">
                    {element.type !== 'qr' && <label><input type="checkbox" checked={element.bold}
                        onChange={e => editElement(i, {bold: e.target.checked})}/> Полужирный</label>}
                    <button className="icon_btn" type="button" onClick={() =>
                        onChange({...draft, elements: elements.filter((_, index) => index !== i)})}>Удалить элемент {i + 1}</button>
                </div>
            </fieldset>)}
            <div className="template_actions">
                <button className="btn btn_secondary" type="button" disabled={elements.length >= 50}
                    onClick={addElement}>Добавить элемент</button>
                <button className="btn btn_primary" type="submit">Сохранить шаблон</button>
            </div>
        </fieldset>
    </form>;
}
