import React, { useState } from 'react';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import {createUser, fetchUsers} from '~/store/reducers/SettingsSlice';
import type {UserOut} from '~/models/api';
import {AdminService} from '~/services/AdminService';
import {parseError} from '~/utils/ParseError';

interface Props {
    onClose: () => void;
    user?: UserOut;
}

export const CreateUserModal = ({onClose, user}: Props) => {
    const dispatch = useAppDispatch();
    const roles = useAppSelector(state => state.settingsReducer.roles);

    const [formData, setFormData] = useState({
        full_name: user?.full_name ?? '',
        login: user?.login ?? '',
        password: '',
        role_id: user?.role.id.toString() ?? '',
    });
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (saving) return;
        if (!formData.full_name.trim() || !formData.role_id || (!user && (!formData.login.trim() || !formData.password))) {
            setError('Заполните все обязательные поля');
            return;
        }

        if (formData.password && formData.password.length < 8) {
            setError('Пароль должен быть не короче 8 символов');
            return;
        }

        setSaving(true);
        setError(null);
        const {full_name, login, password} = formData;
        const fields = {full_name, role_id: Number(formData.role_id)};
        try {
            if (user) {
                await AdminService.updateUser(user.id, {...fields, password: password || undefined});
                void dispatch(fetchUsers());
            } else {
                await dispatch(createUser({...fields, login, password})).unwrap();
            }
            onClose();
        } catch (err: any) {
            setError(user ? parseError(err).message : err?.message || 'Не удалось добавить сотрудника');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{user ? 'Изменить сотрудника' : 'Добавить сотрудника'}</h2>
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
                        readOnly={!!user}
                    />

                    <input
                        className="modal_input"
                        type="password"
                        placeholder={user ? 'Новый пароль (необязательно)' : 'Пароль (от 8 символов) *'}
                        value={formData.password}
                        onChange={e => setFormData({...formData, password: e.target.value})}
                        required={!user}
                        minLength={8}
                        maxLength={128}
                        autoComplete="new-password"
                    />

                    <div>
                        <label style={{ fontSize: '12px', color: 'var(--tpu-gray-text)', marginBottom: '4px', display: 'block' }}>Роль *</label>
                        <select
                            aria-label="Роль"
                            className="modal_input"
                            value={formData.role_id}
                            onChange={e => setFormData({...formData, role_id: e.target.value})}
                            required
                        >
                            <option value="">-- Выберите роль --</option>
                            {user && !roles.some(role => role.id === user.role.id) &&
                                <option value={user.role.id}>{user.role.name}</option>}
                            {roles.map(r => (
                                <option key={r.id} value={r.id}>{r.name}</option>
                            ))}
                        </select>
                    </div>

                    {error && <div style={{ color: 'var(--danger)', fontSize: '14px' }}>{error}</div>}

                    <button type="submit" className="btn btn_primary" disabled={saving} style={{ marginTop: '16px' }}>
                        {user ? 'Сохранить' : 'Создать сотрудника'}
                    </button>
                </form>
            </div>
        </div>
    );
};
