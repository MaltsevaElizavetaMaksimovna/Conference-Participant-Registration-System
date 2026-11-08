import React, {useState} from 'react';
import {useAppDispatch} from '~/hooks/redux';
import {createParticipant} from '~/store/reducers/AdminSlice';

interface Props {
    onClose: () => void;
}

export const AddParticipantModal = ({onClose}: Props) => {
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

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.last_name.trim() || !formData.first_name.trim()) {
            setError('Фамилия и Имя обязательны');
            return;
        }

        try {
            await dispatch(createParticipant(formData)).unwrap();
            onClose();
        } catch (err: any) {
            setError(err.message || 'Ошибка при добавлении');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{maxWidth: '500px'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Добавить участника</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit}
                      style={{padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px'}}>
                    <input className="modal_input" placeholder="Фамилия *" value={formData.last_name}
                           onChange={e => setFormData({...formData, last_name: e.target.value})} required/>
                    <input className="modal_input" placeholder="Имя *" value={formData.first_name}
                           onChange={e => setFormData({...formData, first_name: e.target.value})} required/>
                    <input className="modal_input" placeholder="Отчество" value={formData.middle_name}
                           onChange={e => setFormData({...formData, middle_name: e.target.value})}/>
                    <input className="modal_input" placeholder="Должность" value={formData.position}
                           onChange={e => setFormData({...formData, position: e.target.value})}/>
                    <input className="modal_input" placeholder="Организация" value={formData.organization}
                           onChange={e => setFormData({...formData, organization: e.target.value})}/>

                    <label style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        marginTop: '8px',
                        cursor: 'pointer'
                    }}>
                        <input type="checkbox" checked={formData.with_sticker}
                               onChange={e => setFormData({...formData, with_sticker: e.target.checked})}/>
                        Печатать наклейку сразу
                    </label>

                    {error && <div style={{color: 'var(--danger)', fontSize: '14px'}}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{marginTop: '16px'}}>Добавить</button>
                </form>
            </div>
        </div>
    );
};