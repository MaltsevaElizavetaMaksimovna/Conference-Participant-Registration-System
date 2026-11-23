import React, {useState} from 'react';
import {useAppDispatch} from '~/hooks/redux';
import {createConference, fetchConferences, updateConference} from '~/store/reducers/ConferenceSlice';
import type {ConferenceIn, ConferenceOut} from '~/models/api';

interface Props {
    onClose: () => void;
    conference?: ConferenceOut;
}

export const CreateConferenceModal = ({onClose, conference}: Props) => {
    const dispatch = useAppDispatch();
    const [formData, setFormData] = useState<ConferenceIn>({
        title: conference?.title ?? '', date_from: conference?.date_from ?? '', date_to: conference?.date_to ?? '',
        badge_type: conference?.badge_type ?? 'single', invite_id_regex: conference?.invite_id_regex,
        front_template_id: conference?.front_template_id, back_template_id: conference?.back_template_id,
        changed_template_id: conference?.changed_template_id, changed_back_template_id: conference?.changed_back_template_id,
    });
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (saving) return;
        if (!formData.title.trim() || !formData.date_from || !formData.date_to) {
            setError('Заполните все обязательные поля');
            return;
        }

        setSaving(true);
        setError(null);
        try {
            if (conference) {
                await dispatch(updateConference({id: conference.id, data: formData})).unwrap();
            } else {
                await dispatch(createConference(formData)).unwrap();
            }
            dispatch(fetchConferences({limit: 100, offset: 0}));
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Не удалось сохранить конференцию');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{maxWidth: '500px'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{conference ? 'Изменить конференцию' : 'Создать конференцию'}</h2>
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
                            onChange={e => setFormData({...formData, badge_type: e.target.value as ConferenceIn['badge_type']})}
                        >
                            <option value="single">Односторонний</option>
                            <option value="double">Двусторонний</option>
                            <option value="none">Без бейджа</option>
                        </select>
                    </div>

                    {error && <div style={{color: 'var(--danger)', fontSize: '14px'}}>{error}</div>}

                    <button type="submit" className="btn btn_primary" disabled={saving} style={{marginTop: '16px'}}>
                        {conference ? 'Сохранить' : 'Создать'}
                    </button>
                </form>
            </div>
        </div>
    );
};
