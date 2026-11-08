import React, { useState } from 'react';
import { useAppDispatch } from '~/hooks/redux';
import { createPrinter } from '~/store/reducers/SettingsSlice';

interface Props {
    onClose: () => void;
}

export const CreatePrinterModal = ({ onClose }: Props) => {
    const dispatch = useAppDispatch();
    const [formData, setFormData] = useState({
        name: '',
        windows_printer_name: '',
        dpi: 203,
        density: 10,
        speed: 3,
    });
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.name.trim()) {
            setError('Название принтера обязательно');
            return;
        }

        try {
            await dispatch(createPrinter({
                name: formData.name,
                windows_printer_name: formData.windows_printer_name || null,
                dpi: formData.dpi,
                density: formData.density,
                speed: formData.speed,
                offset_x_mm: 0,
                offset_y_mm: 0,
            })).unwrap();
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Ошибка при создании принтера');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Добавить принтер</h2>
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

                    <div style={{ display: 'flex', gap: '12px' }}>
                        <div style={{ flex: 1 }}>
                            <label style={{ fontSize: '12px', color: 'var(--tpu-gray-text)', marginBottom: '4px', display: 'block' }}>DPI (разрешение)</label>
                            <input
                                type="number"
                                className="modal_input"
                                value={formData.dpi}
                                onChange={e => setFormData({...formData, dpi: Number(e.target.value)})}
                            />
                        </div>
                        <div style={{ flex: 1 }}>
                            <label style={{ fontSize: '12px', color: 'var(--tpu-gray-text)', marginBottom: '4px', display: 'block' }}>Плотность (0-15)</label>
                            <input
                                type="number"
                                className="modal_input"
                                value={formData.density}
                                onChange={e => setFormData({...formData, density: Number(e.target.value)})}
                            />
                        </div>
                    </div>

                    {error && <div style={{ color: 'var(--danger)', fontSize: '14px' }}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{ marginTop: '16px' }}>Добавить принтер</button>
                </form>
            </div>
        </div>
    );
};