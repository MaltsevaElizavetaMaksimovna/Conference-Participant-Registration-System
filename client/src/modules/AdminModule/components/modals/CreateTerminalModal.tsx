import React, {useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {createTerminal, fetchTerminals} from '~/store/reducers/SettingsSlice';
import type {TerminalOut} from '~/models/api';
import {AdminService} from '~/services/AdminService';
import {parseError} from '~/utils/ParseError';

interface Props {
    onClose: () => void;
    terminal?: TerminalOut;
}

export const CreateTerminalModal = ({onClose, terminal}: Props) => {
    const dispatch = useAppDispatch();
    const printers = useAppSelector(state => state.settingsReducer.printers);

    const [formData, setFormData] = useState({
        name: terminal?.name ?? '',
        printer_id: terminal?.printer_id?.toString() ?? '',
        enabled: terminal?.enabled ?? true,
    });
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (saving) return;
        if (!formData.name.trim()) {
            setError('Название терминала обязательно');
            return;
        }

        setSaving(true);
        setError(null);
        const input = {...formData, printer_id: formData.printer_id ? Number(formData.printer_id) : null};
        try {
            if (terminal) {
                await AdminService.updateTerminal(terminal.id, input);
                void dispatch(fetchTerminals());
            } else {
                await dispatch(createTerminal(input)).unwrap();
            }
            onClose();
        } catch (err: any) {
            setError(terminal ? parseError(err).message : err?.message || 'Не удалось добавить терминал');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{maxWidth: '500px'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{terminal ? 'Изменить терминал' : 'Добавить терминал'}</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit}
                      style={{padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px'}}>
                    <input
                        className="modal_input"
                        placeholder="Название (например, Терминал 1) *"
                        value={formData.name}
                        onChange={e => setFormData({...formData, name: e.target.value})}
                        required
                    />

                    <div>
                        <label style={{
                            fontSize: '12px',
                            color: 'var(--tpu-gray-text)',
                            marginBottom: '4px',
                            display: 'block'
                        }}>Привязанный принтер</label>
                        <select
                            aria-label="Привязанный принтер"
                            className="modal_input"
                            value={formData.printer_id}
                            onChange={e => setFormData({...formData, printer_id: e.target.value})}
                        >
                            <option value="">-- Не привязан --</option>
                            {terminal?.printer_id && !printers.some(printer => printer.id === terminal.printer_id) &&
                                <option value={terminal.printer_id}>Текущий принтер №{terminal.printer_id}</option>}
                            {printers.map(p => (
                                <option key={p.id} value={p.id}>{p.name} ({p.status})</option>
                            ))}
                        </select>
                    </div>

                    <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer'}}>
                        <input
                            type="checkbox"
                            checked={formData.enabled}
                            onChange={e => setFormData({...formData, enabled: e.target.checked})}
                        />
                        Терминал включен (принимает коды)
                    </label>

                    {error && <div style={{color: 'var(--danger)', fontSize: '14px'}}>{error}</div>}

                    <button type="submit" className="btn btn_primary" disabled={saving} style={{marginTop: '16px'}}>
                        {terminal ? 'Сохранить' : 'Добавить'}
                    </button>
                </form>
            </div>
        </div>
    );
};
