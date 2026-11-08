import React, {useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {createTerminal} from '~/store/reducers/SettingsSlice';

interface Props {
    onClose: () => void;
}

export const CreateTerminalModal = ({onClose}: Props) => {
    const dispatch = useAppDispatch();
    const printers = useAppSelector(state => state.settingsReducer.printers);

    const [formData, setFormData] = useState({
        name: '',
        printer_id: '' as string | number,
        enabled: true,
    });
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.name.trim()) {
            setError('Название терминала обязательно');
            return;
        }

        try {
            await dispatch(createTerminal({
                name: formData.name,
                enabled: formData.enabled,
                printer_id: formData.printer_id ? Number(formData.printer_id) : null,
            })).unwrap();
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Ошибка при создании терминала');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{maxWidth: '500px'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Добавить терминал</h2>
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
                            className="modal_input"
                            value={formData.printer_id}
                            onChange={e => setFormData({...formData, printer_id: e.target.value})}
                        >
                            <option value="">-- Не привязан --</option>
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

                    <button type="submit" className="btn btn_primary" style={{marginTop: '16px'}}>Добавить</button>
                </form>
            </div>
        </div>
    );
};