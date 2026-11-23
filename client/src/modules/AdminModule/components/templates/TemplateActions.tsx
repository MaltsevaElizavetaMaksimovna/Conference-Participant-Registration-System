import type {FormEvent} from 'react';
import type {ConferenceOut, ResizeIn, TemplateOut} from '~/models/api';

export function TemplateActions({template, targets, blocked, bound, onCopy, onResize, onBind}: {
    template: TemplateOut; targets: ConferenceOut[]; blocked: boolean; bound: boolean;
    onCopy: (id: number) => void; onResize: (size: ResizeIn) => void; onBind: () => void;
}) {
    function resize(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        onResize({width_mm: Number(values.get('width')), height_mm: Number(values.get('height'))});
    }
    function copy(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const id = Number(new FormData(event.currentTarget).get('conference'));
        if (targets.some(target => target.id === id)) onCopy(id);
    }
    return <section className="template_fields" aria-label="Действия с сохранённым шаблоном">
        <div className="template_actions">
            <button className="btn btn_secondary" type="button" disabled={blocked} onClick={onBind}>
                {bound ? 'Снять назначение' : 'Назначить конференции'}
            </button>
            {bound && <span>Используется для печати</span>}
        </div>
        <form className="template_actions" onSubmit={copy}>
            <label>Конференция для копии<select className="input" name="conference" defaultValue="" required
                disabled={blocked || !targets.length}>
                <option value="">Выберите конференцию</option>
                {targets.map(target => <option key={target.id} value={target.id}>{target.title}</option>)}
            </select></label>
            <button className="btn btn_secondary" type="submit" disabled={blocked || !targets.length}>Копировать</button>
        </form>
        <form className="template_actions" key={template.version} onSubmit={resize}>
            <label>Новая ширина, мм<input className="input" name="width" type="number" required
                min="0.01" max="200" step="0.01" defaultValue={template.width_mm} disabled={blocked}/></label>
            <label>Новая высота, мм<input className="input" name="height" type="number" required
                min="0.01" max="200" step="0.01" defaultValue={template.height_mm} disabled={blocked}/></label>
            <button className="btn btn_secondary" type="submit" disabled={blocked}>Масштабировать</button>
        </form>
    </section>;
}
