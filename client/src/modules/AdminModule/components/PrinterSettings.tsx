import {useState} from 'react';
import {useAppDispatch} from '~/hooks/redux';
import type {PrinterAdminOut} from '~/models/api';
import {AdminService} from '~/services/AdminService';
import {fetchPrinters} from '~/store/reducers/SettingsSlice';
import {parseError} from '~/utils/ParseError';
import {TerminalTokenModal} from './modals/TerminalTokenModal';

export function PrinterSettings({printers, onEdit}: {printers: PrinterAdminOut[]; onEdit: (printer: PrinterAdminOut) => void}) {
    const dispatch = useAppDispatch();
    const [issuing, setIssuing] = useState(false);
    const [token, setToken] = useState<string | null>(null);
    const [error, setError] = useState('');

    async function issueToken(printer: PrinterAdminOut) {
        if (issuing || !window.confirm(printer.token_set
            ? 'Заменить токен агента? Предыдущий токен перестанет работать.' : 'Выдать токен агенту выбранного принтера?')) return;
        setIssuing(true);
        setError('');
        try {
            const {data} = await AdminService.issuePrinterToken(printer.id);
            setToken(data.token);
            void dispatch(fetchPrinters());
        } catch (error) {
            setError(parseError(error).message);
        } finally {
            setIssuing(false);
        }
    }

    return <section>
        <h2>Принтеры</h2>
        {error && <p role="alert">{error}</p>}
        <div className="table_wrapper">
            <table className="table" aria-label="Принтеры">
                <thead><tr><th>Название</th><th>Имя в Windows</th><th>Токен агента</th><th>Действия</th></tr></thead>
                <tbody>
                    {printers.map(printer => <tr key={printer.id}>
                        <td>{printer.name}</td><td>{printer.windows_printer_name || '—'}</td>
                        <td>{printer.token_set ? 'Выдан' : 'Отсутствует'}</td>
                        <td><div className="actions_cell">
                            <button className="icon_btn" onClick={() => onEdit(printer)}>Изменить</button>
                            <button className="icon_btn" disabled={issuing} onClick={() => void issueToken(printer)}>
                                {printer.token_set ? 'Заменить токен' : 'Выдать токен'}
                            </button>
                        </div></td>
                    </tr>)}
                    {printers.length === 0 && <tr><td colSpan={4}>Принтеров пока нет</td></tr>}
                </tbody>
            </table>
        </div>
        {token && <TerminalTokenModal token={token} title="Токен агента печати" onClose={() => setToken(null)}/>}
    </section>;
}
