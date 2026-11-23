import React, { useState } from 'react';
import { useAppDispatch } from '~/hooks/redux';
import {createPrinter, fetchPrinters} from '~/store/reducers/SettingsSlice';
import type {PrinterAdminOut} from '~/models/api';
import {AdminService} from '~/services/AdminService';
import {parseError} from '~/utils/ParseError';

const printerFields = [
    ['dpi', 'Разрешение, DPI', 100, 1200, 1],
    ['density', 'Плотность', 0, 15, 1],
    ['speed', 'Скорость', 1, 6, 1],
    ['offset_x_mm', 'Сдвиг по X, мм', -50, 50, 0.01],
    ['offset_y_mm', 'Сдвиг по Y, мм', -50, 50, 0.01],
] as const;

interface Props {
    onClose: () => void;
    printer?: PrinterAdminOut;
}

export const CreatePrinterModal = ({onClose, printer}: Props) => {
    const dispatch = useAppDispatch();
    const [formData, setFormData] = useState({
        name: printer?.name ?? '', windows_printer_name: printer?.windows_printer_name ?? '',
        dpi: printer?.dpi ?? 203, density: printer?.density ?? 10, speed: printer?.speed ?? 3,
        offset_x_mm: printer?.offset_x_mm ?? 0, offset_y_mm: printer?.offset_y_mm ?? 0,
    });
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (saving) return;
        if (!formData.name.trim()) {
            setError('Название принтера обязательно');
            return;
        }

        setSaving(true);
        setError(null);
        const input = {...formData, windows_printer_name: formData.windows_printer_name.trim() || null};
        try {
            if (printer) {
                await AdminService.updatePrinter(printer.id, input);
                void dispatch(fetchPrinters());
            } else {
                await dispatch(createPrinter(input)).unwrap();
            }
            onClose();
        } catch (err: any) {
            setError(printer ? parseError(err).message : err?.message || 'Не удалось добавить принтер');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{printer ? 'Изменить принтер' : 'Добавить принтер'}</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <input
                        className="modal_input"
                        placeholder="Название принтера (например, Принтер 1) *"
                        value={formData.name}
                        onChange={e => setFormData({...formData, name: e.target.value})}
                        required
                    />

                    <input
                        className="modal_input"
                        placeholder="Имя в Windows (например, XP-360B)"
                        value={formData.windows_printer_name}
                        onChange={e => setFormData({...formData, windows_printer_name: e.target.value})}
                    />

                    <div className="template_grid">
                        {printerFields.map(([key, label, min, max, step]) => <label key={key}>{label}
                            <input className="modal_input" type="number" required min={min} max={max} step={step}
                                value={Number.isFinite(formData[key]) ? formData[key] : ''}
                                onChange={e => setFormData({...formData, [key]: e.target.valueAsNumber})}/>
                        </label>)}
                    </div>

                    {error && <div style={{ color: 'var(--danger)', fontSize: '14px' }}>{error}</div>}

                    <button type="submit" className="btn btn_primary" disabled={saving} style={{marginTop: '16px'}}>
                        {printer ? 'Сохранить' : 'Добавить принтер'}
                    </button>
                </form>
            </div>
        </div>
    );
};
