import {useEffect, useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {fetchPrinters} from '~/store/reducers/AdminSlice';
import {setPanelPrinter} from '~/store/reducers/AuthSlice';

export function PanelPrinterSelect() {
    const dispatch = useAppDispatch();
    const printers = useAppSelector(state => state.adminReducer.printers);
    const printerId = useAppSelector(state => state.authReducer.user?.panel_printer_id ?? null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        const request = dispatch(fetchPrinters());
        void request.then(result => {
            if (fetchPrinters.rejected.match(result) && result.meta.aborted) return;
            if (fetchPrinters.rejected.match(result)) {
                setError(result.payload?.message ?? 'Не удалось загрузить принтеры');
                return;
            }
            setLoading(false);
        });
        return () => request.abort();
    }, [dispatch]);

    async function selectPrinter(value: string) {
        setSaving(true);
        setError('');
        const result = await dispatch(setPanelPrinter(value ? Number(value) : null));
        if (setPanelPrinter.rejected.match(result)) {
            setError(result.payload?.message ?? 'Не удалось сохранить принтер');
        }
        setSaving(false);
    }

    return <div className="panel_printer">
        <label>Принтер стойки{' '}
            <select className="input" value={printerId ?? ''} disabled={loading || saving}
                    onChange={event => void selectPrinter(event.target.value)}>
                <option value="">Без принтера</option>
                {printerId !== null && !printers.some(printer => printer.id === printerId) &&
                    <option value={printerId} disabled>Принтер недоступен</option>}
                {printers.map(printer => <option key={printer.id} value={printer.id}>{printer.name}</option>)}
            </select>
        </label>
        {error && <p role="alert">{error}</p>}
    </div>;
}
