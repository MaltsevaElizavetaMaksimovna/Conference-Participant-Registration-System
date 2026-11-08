import React, { useState } from 'react';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import { createUser } from '~/store/reducers/SettingsSlice';

interface Props {
    onClose: () => void;
}

export const CreateUserModal = ({ onClose }: Props) => {
    const dispatch = useAppDispatch();
    const roles = useAppSelector(state => state.settingsReducer.roles);

    const [formData, setFormData] = useState({
        full_name: '',
        login: '',
        password: '',
        role_id: '' as string | number,
    });
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!formData.full_name.trim() || !formData.login.trim() || !formData.password.trim() || !formData.role_id) {
            setError('Заполните все обязательные поля');
            return;
        }

        if (formData.password.length < 8) {
            setError('Пароль должен быть не короче 8 символов');
            return;
        }

        try {
            await dispatch(createUser({
                full_name: formData.full_name,
                login: formData.login,
                password: formData.password,
                role_id: Number(formData.role_id),
            })).unwrap();
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Ошибка при создании сотрудника');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Добавить сотрудника</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <input
                        className="modal_input"
                        placeholder="ФИО сотрудника *"
                        value={formData.full_name}
                        onChange={e => setFormData({...formData, full_name: e.target.value})}
                        required
                    />

                    <input
                        className="modal_input"
                        placeholder="Логин *"
                        value={formData.login}
                        onChange={e => setFormData({...formData, login: e.target.value})}
                        required
                    />

                    <input
                        className="modal_input"
                        type="password"
                        placeholder="Пароль (от 8 символов) *"
                        value={formData.password}
                        onChange={e => setFormData({...formData, password: e.target.value})}
                        required
                    />

                    <div>
                        <label style={{ fontSize: '12px', color: 'var(--tpu-gray-text)', marginBottom: '4px', display: 'block' }}>Роль *</label>
                        <select
                            className="modal_input"
                            value={formData.role_id}
                            onChange={e => setFormData({...formData, role_id: e.target.value})}
                            required
                        >
                            <option value="">-- Выберите роль --</option>
                            {roles.map(r => (
                                <option key={r.id} value={r.id}>{r.name}</option>
                            ))}
                        </select>
                    </div>

                    {error && <div style={{ color: 'var(--danger)', fontSize: '14px' }}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{ marginTop: '16px' }}>Создать сотрудника</button>
                </form>
            </div>
        </div>
    );
};