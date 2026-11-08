import React, {useState} from 'react';
import {useAppDispatch} from '~/hooks/redux';
import {createConference, fetchConferences} from '~/store/reducers/ConferenceSlice';

interface Props {
    onClose: () => void;
}

export const CreateConferenceModal = ({onClose}: Props) => {
    const dispatch = useAppDispatch();
    const [formData, setFormData] = useState({
        title: '',
        date_from: '',
        date_to: '',
        badge_type: 'single' as 'single' | 'double' | 'none',
    });
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.title.trim() || !formData.date_from || !formData.date_to) {
            setError('Заполните все обязательные поля');
            return;
        }

        try {
            await dispatch(createConference(formData)).unwrap();
            dispatch(fetchConferences({limit: 100, offset: 0}));
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Ошибка при создании');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{maxWidth: '500px'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Создать конференцию</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit}
                      style={{padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px'}}>
                    <input
                        className="modal_input"
                        placeholder="Название конференции *"
                        value={formData.title}
                        onChange={e => setFormData({...formData, title: e.target.value})}
                        required
                    />

                    <div style={{display: 'flex', gap: '12px'}}>
                        <div style={{flex: 1}}>
                            <label style={{
                                fontSize: '12px',
                                color: 'var(--tpu-gray-text)',
                                marginBottom: '4px',
                                display: 'block'
                            }}>Дата начала *</label>
                            <input
                                type="date"
                                className="modal_input"
                                value={formData.date_from}
                                onChange={e => setFormData({...formData, date_from: e.target.value})}
                                required
                            />
                        </div>
                        <div style={{flex: 1}}>
                            <label style={{
                                fontSize: '12px',
                                color: 'var(--tpu-gray-text)',
                                marginBottom: '4px',
                                display: 'block'
                            }}>Дата окончания *</label>
                            <input
                                type="date"
                                className="modal_input"
                                value={formData.date_to}
                                onChange={e => setFormData({...formData, date_to: e.target.value})}
                                required
                            />
                        </div>
                    </div>

                    <div>
                        <label style={{
                            fontSize: '12px',
                            color: 'var(--tpu-gray-text)',
                            marginBottom: '4px',
                            display: 'block'
                        }}>Тип бейджа</label>
                        <select
                            className="modal_input"
                            value={formData.badge_type}
                            onChange={e => setFormData({...formData, badge_type: e.target.value as any})}
                        >
                            <option value="single">Односторонний</option>
                            <option value="double">Двусторонний</option>
                            <option value="none">Без бейджа</option>
                        </select>
                    </div>

                    {error && <div style={{color: 'var(--danger)', fontSize: '14px'}}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{marginTop: '16px'}}>Создать</button>
                </form>
            </div>
        </div>
    );
};