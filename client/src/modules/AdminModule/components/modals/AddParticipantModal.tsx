import React, { useState } from 'react';
import { useAppDispatch } from '~/hooks/redux';
import { createParticipant, checkDuplicates } from '~/store/reducers/AdminSlice';
import type { ParticipantShort } from '~/models/api';

interface Props {
    onClose: () => void;
}

export const AddParticipantModal = ({ onClose }: Props) => {
    const dispatch = useAppDispatch();
    const [formData, setFormData] = useState({
        last_name: '',
        first_name: '',
        middle_name: '',
        position: '',
        organization: '',
        with_sticker: true,
    });

    const [error, setError] = useState<string | null>(null);
    const [isChecking, setIsChecking] = useState(false);
    const [duplicates, setDuplicates] = useState<ParticipantShort[] | null>(null);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.last_name.trim() || !formData.first_name.trim()) {
            setError('Фамилия и Имя обязательны');
            return;
        }

        setIsChecking(true);
        setError(null);

        try {
            const result = await dispatch(checkDuplicates({
                last_name: formData.last_name.trim(),
                first_name: formData.first_name.trim(),
            })).unwrap();

            if (result.items && result.items.length > 0) {
                setDuplicates(result.items);
            } else {
                await saveParticipant();
            }
        } catch (err: any) {
            setError(err?.message || 'Ошибка при проверке дублей');
        } finally {
            setIsChecking(false);
        }
    };

    const saveParticipant = async () => {
        try {
            await dispatch(createParticipant(formData)).unwrap();
            onClose();
        } catch (err: any) {
            setError(err.message || 'Ошибка при добавлении');
        }
    };

    if (duplicates) {
        return (
            <div className="add_user_modal_container" onClick={onClose}>
                <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
                    <div className="add_user_modal_header">
                        <h2 className="add_user_modal_title">Возможно, участник уже есть в списке</h2>
                        <button className="icon_btn" onClick={onClose}>✖</button>
                    </div>

                    <div style={{ padding: '24px' }}>
                        <p style={{ marginBottom: '16px', color: 'var(--tpu-gray-text)' }}>
                            Мы нашли похожих участников. Пожалуйста, проверьте, нет ли его среди них.
                        </p>

                        <div className="table_wrapper" style={{ maxHeight: '300px', marginBottom: '24px' }}>
                            <table className="table">
                                <thead>
                                <tr>
                                    <th>ФИО</th>
                                    <th>Организация</th>
                                    <th>Статус</th>
                                </tr>
                                </thead>
                                <tbody>
                                {duplicates.map(d => (
                                    <tr key={d.id}>
                                        <td>{d.full_name}</td>
                                        <td>{d.organization || '—'}</td>
                                        <td>
                                                <span className={`badge ${
                                                    d.status === 'registered' ? 'badge_success' :
                                                        d.status === 'registered_no_sticker' ? 'badge_warn' : 'badge_muted'
                                                }`}>
                                                    {d.status === 'registered' ? 'Зарегистрирован' :
                                                        d.status === 'registered_no_sticker' ? 'Без наклейки' : 'Не пришел'}
                                                </span>
                                        </td>
                                    </tr>
                                ))}
                                </tbody>
                            </table>
                        </div>

                        <div style={{ display: 'flex', gap: '12px' }}>
                            <button className="btn btn_secondary" onClick={() => setDuplicates(null)}>
                                Вернуться к редактированию
                            </button>
                            <button className="btn btn_danger" onClick={saveParticipant}>
                                Всё равно добавить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Добавить участника</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <input className="modal_input" placeholder="Фамилия *" value={formData.last_name} onChange={e => setFormData({...formData, last_name: e.target.value})} required />
                    <input className="modal_input" placeholder="Имя *" value={formData.first_name} onChange={e => setFormData({...formData, first_name: e.target.value})} required />
                    <input className="modal_input" placeholder="Отчество" value={formData.middle_name} onChange={e => setFormData({...formData, middle_name: e.target.value})} />
                    <input className="modal_input" placeholder="Должность" value={formData.position} onChange={e => setFormData({...formData, position: e.target.value})} />
                    <input className="modal_input" placeholder="Организация" value={formData.organization} onChange={e => setFormData({...formData, organization: e.target.value})} />

                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', cursor: 'pointer' }}>
                        <input type="checkbox" checked={formData.with_sticker} onChange={e => setFormData({...formData, with_sticker: e.target.checked})} />
                        Печатать наклейку сразу
                    </label>

                    {error && <div style={{ color: 'var(--danger)', fontSize: '14px' }}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{ marginTop: '16px' }} disabled={isChecking}>
                        {isChecking ? 'Проверка дублей...' : 'Добавить'}
                    </button>
                </form>
            </div>
        </div>
    );
};