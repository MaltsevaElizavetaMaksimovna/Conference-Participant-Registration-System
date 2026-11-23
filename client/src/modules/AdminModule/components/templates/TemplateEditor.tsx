import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router';
import type {ConferenceOut, ResizeIn, TemplateFieldOut, TemplateIn, TemplateOut} from '~/models/api';
import type {Errors} from '~/models/Errors';
import ConferenceService from '~/services/ConferenceService';
import {TemplateService} from '~/services/TemplateService';
import {parseError} from '~/utils/ParseError';
import {TemplateActions} from './TemplateActions';
import {TemplateForm, templateKinds} from './TemplateForm';
import {TemplateOutput} from './TemplateOutput';
import './template-editor.css';

const settings = '/admin/settings';
const bindingForKind = {
    front: 'front_template_id', back: 'back_template_id',
    changed: 'changed_template_id', changed_back: 'changed_back_template_id',
} as const;

interface EditorData {
    conference: ConferenceOut;
    templates: TemplateOut[];
    fields: TemplateFieldOut[];
    targets: ConferenceOut[];
}

async function loadCopyTargets(conferenceId: number, signal: AbortSignal) {
    const items: ConferenceOut[] = [];
    while (true) {
        const {data} = await ConferenceService.list(100, items.length, signal);
        items.push(...data.items);
        if (!data.items.length || items.length >= data.total) return items.filter(item => item.id !== conferenceId);
    }
}

const newDraft = (): TemplateIn => ({name: '', kind: 'front', width_mm: 60, height_mm: 40, gap_mm: 2, elements: []});

function editDraft(template: TemplateOut): TemplateIn {
    const {name, kind, width_mm, height_mm, gap_mm, elements} = template;
    return {name, kind, width_mm, height_mm, gap_mm, elements};
}

function ShowError({error}: {error: Errors}) {
    const fields = error.details?.fields;
    const messages = fields && typeof fields === 'object' ? Object.values(fields).filter(value => typeof value === 'string') : [];
    return <div role="alert" className="template_error">
        <p>{error.message}</p>
        {!!messages.length && <ul>{messages.map((message, index) => <li key={index}>{message}</li>)}</ul>}
    </div>;
}

export function TemplateEditor({conferenceId}: {conferenceId: number}) {
    const [data, setData] = useState<EditorData | null>(null);
    const [error, setError] = useState<Errors | null>(null);
    const [attempt, setAttempt] = useState(0);
    const [busy, setBusy] = useState(false);
    const busyRef = useRef(false);
    const [selected, setSelected] = useState<TemplateOut | null>(null);
    const [draft, setDraft] = useState<TemplateIn | null>(null);
    const [dirty, setDirty] = useState(false);
    const [notice, setNotice] = useState('');
    const [copyTarget, setCopyTarget] = useState<number | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        const {signal} = controller;
        Promise.all([
            ConferenceService.getById(conferenceId, signal), TemplateService.list(conferenceId, signal),
            TemplateService.fields(conferenceId, signal), loadCopyTargets(conferenceId, signal),
        ]).then(([{data: conference}, templates, fields, targets]) => {
            if (!signal.aborted) setData({conference, templates, fields, targets});
        }).catch(error => {
            if (!signal.aborted) setError(parseError(error));
        });
        return () => controller.abort();
    }, [attempt, conferenceId]);

    function open(template: TemplateOut | null) {
        if (dirty && !window.confirm('Отменить несохранённые изменения шаблона?')) return;
        setSelected(template);
        setDraft(template ? editDraft(template) : newDraft());
        setDirty(false);
        setError(null);
        setNotice('');
        setCopyTarget(null);
    }

    async function run<T>(operation: () => Promise<T>): Promise<T | undefined> {
        if (busyRef.current) return;
        busyRef.current = true;
        setBusy(true);
        setError(null);
        setNotice('');
        setCopyTarget(null);
        try {
            return await operation();
        } catch (error) {
            setError(parseError(error));
        } finally {
            busyRef.current = false;
            setBusy(false);
        }
    }

    function applySaved(template: TemplateOut) {
        setData(current => {
            if (!current) return current;
            const templates = current.templates.some(item => item.id === template.id)
                ? current.templates.map(item => item.id === template.id ? template : item)
                : [...current.templates, template];
            return {...current, templates};
        });
        setSelected(template);
        setDraft(editDraft(template));
        setDirty(false);
        setNotice('Шаблон сохранён');
    }

    function save(input: TemplateIn) {
        void run(async () => {
            const saved = selected ? await TemplateService.save(selected, input) : await TemplateService.create(conferenceId, input);
            applySaved(saved);
        });
    }

    function resize(template: TemplateOut, size: ResizeIn) {
        void run(async () => applySaved(await TemplateService.resize(template, size)));
    }

    function copy(template: TemplateOut, targetId: number) {
        void run(async () => {
            await TemplateService.copy(template, targetId);
            setNotice('Копия создана');
            setCopyTarget(targetId);
        });
    }

    function bind(template: TemplateOut) {
        void run(async () => {
            const {data: conference} = await ConferenceService.getById(conferenceId);
            const {id, is_active, participants_total, created_at, ...input} = conference;
            const key = bindingForKind[template.kind];
            const assign = input[key] !== template.id;
            const {data: updated} = await ConferenceService.update(id, {...input, [key]: assign ? template.id : null});
            setData(current => current && {...current, conference: updated});
            setNotice(assign ? 'Шаблон назначен конференции' : 'Назначение снято');
        });
    }

    const bound = !!(selected && data?.conference[bindingForKind[selected.kind]] === selected.id);
    const blocked = busy || dirty;
    return <main className="admin_main template_editor">
        <Link to={settings}>К списку конференций</Link>
        <h1>Шаблоны наклеек</h1>
        {data && <p>{data.conference.title}</p>}
        {!data && !error && <p role="status">Загрузка шаблонов…</p>}
        {!data && error && <>
            <ShowError error={error}/>
            <button className="icon_btn" onClick={() => { setError(null); setAttempt(value => value + 1); }}>Повторить</button>
        </>}
        {data && <>
            <div className="template_actions">
                <label>Сохранённый шаблон<select className="input" value={selected?.id ?? ''} disabled={busy}
                    onChange={event => open(data.templates.find(item => item.id === Number(event.target.value)) ?? null)}>
                    <option value="" disabled>Выберите шаблон</option>
                    {data.templates.map(item => <option key={item.id} value={item.id}>
                        {item.name} · {templateKinds[item.kind]}</option>)}
                </select></label>
                <button className="btn btn_secondary" disabled={busy} onClick={() => open(null)}>Новый шаблон</button>
            </div>
            {error && <ShowError error={error}/>}
            {notice && <p role="status">{notice}{copyTarget !== null && <>{' '}
                <Link to={`${settings}?templates=${copyTarget}`}>Открыть конференцию</Link></>}</p>}
            {draft && <div className="template_columns">
                <div>
                    <TemplateForm draft={draft} fields={data.fields} busy={busy} bound={bound} onSave={() => save(draft)}
                        onChange={value => { setDraft(value); setDirty(true); }}/>
                    {!!selected?.warnings?.length && <ul className="template_warnings" aria-label="Предупреждения">
                        {selected.warnings.map(warning => <li key={warning.element}>{warning.message}</li>)}
                    </ul>}
                    {selected && <TemplateActions key={selected.id} template={selected} targets={data.targets}
                        blocked={blocked} bound={bound} onBind={() => bind(selected)}
                        onCopy={targetId => copy(selected, targetId)} onResize={size => resize(selected, size)}/>}
                </div>
                {selected && <TemplateOutput key={selected.id} template={selected} blocked={blocked}
                    onPrint={input => run(() => TemplateService.testPrint(selected, input))}/>}
            </div>}
        </>}
    </main>;
}
