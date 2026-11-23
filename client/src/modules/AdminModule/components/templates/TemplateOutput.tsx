import {useEffect, useState} from 'react';
import type {FormEvent} from 'react';
import type {OverflowItem, PrinterOut, PrintJobOut, PrintJobRefOut, TemplateOut, TemplateTestPrintIn} from '~/models/api';
import {DeskService} from '~/services/DeskService';
import {TemplateService} from '~/services/TemplateService';
import {parseError} from '~/utils/ParseError';

const printStatuses: Record<PrintJobOut['status'], string> = {
    pending: 'В очереди', sent: 'Передано агенту', done: 'Передано принтеру', error: 'Ошибка печати',
};

function TestPrintStatus({jobId}: {jobId: number}) {
    const [job, setJob] = useState<PrintJobOut | null>(null);
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        const controller = new AbortController();
        let timer: number | undefined;
        async function poll() {
            try {
                const {data} = await DeskService.getPrintJob(jobId, controller.signal);
                if (controller.signal.aborted) return;
                setJob(data);
                if (data.status === 'pending' || data.status === 'sent') timer = window.setTimeout(poll, 1000);
            } catch (error) {
                if (!controller.signal.aborted) setError(parseError(error).message);
            }
        }
        void poll();
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [attempt, jobId]);
    return <div className="template_actions">
        <p role="status">Задание №{jobId}. {job ? printStatuses[job.status] : 'Получаем статус…'}
            {job?.error ? ` — ${job.error}` : ''}</p>
        {error && <><span role="alert">{error}</span>
            <button className="icon_btn" type="button" onClick={() => {
                setError('');
                setAttempt(value => value + 1);
            }}>Обновить статус</button></>}
    </div>;
}

function PreviewImage({url}: {url: string}) {
    const [failed, setFailed] = useState(false);
    const [attempt, setAttempt] = useState(0);
    if (failed) return <div className="template_actions">
        <p role="alert">Не удалось загрузить изображение. Проверьте ID участника и подключение.</p>
        <button className="icon_btn" type="button" onClick={() => {
            setFailed(false);
            setAttempt(value => value + 1);
        }}>Повторить загрузку PNG</button>
    </div>;
    return <img key={attempt} className="template_preview" src={url} alt="Предпросмотр наклейки"
        onError={() => setFailed(true)}/>;
}

export function TemplateOutput({template, blocked, onPrint}: {
    template: TemplateOut; blocked: boolean;
    onPrint: (input: TemplateTestPrintIn) => Promise<PrintJobRefOut | undefined>;
}) {
    const [overflow, setOverflow] = useState<OverflowItem[] | null>(null);
    const [overflowError, setOverflowError] = useState('');
    const [printers, setPrinters] = useState<PrinterOut[]>([]);
    const [printersError, setPrintersError] = useState('');
    const [participantId, setParticipantId] = useState<number | null>(null);
    const [jobId, setJobId] = useState<number | null>(null);
    const url = TemplateService.previewUrl(template, participantId);

    useEffect(() => {
        const controller = new AbortController();
        setOverflow(null);
        setOverflowError('');
        TemplateService.overflow(template, controller.signal).then(setOverflow).catch(error => {
            if (!controller.signal.aborted) setOverflowError(parseError(error).message);
        });
        return () => controller.abort();
    }, [template]);

    useEffect(() => {
        let active = true;
        DeskService.listPrinters().then(({data}) => {
            if (active) setPrinters(data);
        }).catch(error => {
            if (active) setPrintersError(parseError(error).message);
        });
        return () => { active = false; };
    }, []);

    function preview(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const value = new FormData(event.currentTarget).get('participant');
        setParticipantId(value ? Number(value) : null);
    }

    async function print(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const printerId = Number(data.get('printer'));
        if (!printerId || !window.confirm('Поставить пробную наклейку в очередь выбранного принтера?')) return;
        const result = await onPrint({printer_id: printerId, participant_id: participantId});
        if (result) setJobId(result.print_job_id);
    }

    return <section className="template_fields" aria-label="Предпросмотр и печать">
        <h2>Предпросмотр · версия {template.version}</h2>
        <form onSubmit={preview} className="template_actions">
            <label>ID участника для образца<input name="participant" className="input" type="number" min="1" step="1"
                max={Number.MAX_SAFE_INTEGER}/></label>
            <button className="btn btn_secondary" type="submit">Обновить предпросмотр</button>
        </form>
        <PreviewImage key={url} url={url}/>
        <h3>Переполнение</h3>
        {overflowError && <p role="alert">{overflowError}</p>}
        {!overflowError && overflow === null && <p role="status">Проверяем размеры полей…</p>}
        {overflow?.length === 0 && <p>Данные участников помещаются.</p>}
        {!!overflow?.length && <ul className="template_overflow">
            {overflow.map(item => <li key={`${item.participant_id}-${item.field}`}>
                <button type="button" className="icon_btn" onClick={() => setParticipantId(item.participant_id)}>
                    {item.full_name}</button> {item.field} — {item.value}
            </li>)}
        </ul>}
        <form onSubmit={print} className="template_actions">
            <label>Принтер для пробы<select className="input" name="printer" defaultValue="" required disabled={blocked}>
                <option value="">Выберите принтер</option>
                {printers.map(printer => <option key={printer.id} value={printer.id}>{printer.name}</option>)}
            </select></label>
            <button className="btn btn_secondary" type="submit" disabled={blocked || !printers.length}>
                Пробная печать</button>
        </form>
        {printersError && <p role="alert">{printersError}</p>}
        {jobId !== null && <TestPrintStatus key={jobId} jobId={jobId}/>}
    </section>;
}
