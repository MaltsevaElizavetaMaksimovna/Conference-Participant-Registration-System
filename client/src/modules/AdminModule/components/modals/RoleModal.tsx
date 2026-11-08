import React, {useState, useEffect} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {createRole, updateRole, fetchPermissions} from '~/store/reducers/SettingsSlice';
import type {RoleOut} from '~/models/api';

interface Props {
    role?: RoleOut | null;
    onClose: () => void;
}

export const RoleModal = ({role, onClose}: Props) => {
    const dispatch = useAppDispatch();
    const permissions = useAppSelector(state => state.settingsReducer.permissions);

    const [name, setName] = useState(role?.name || '');
    const [selectedPerms, setSelectedPerms] = useState<string[]>(role?.permissions || []);
    const [error, setError] = useState<string | null>(null);

    // useEffect(() => {
    //     if (permissions.length === 0) {
    //         dispatch(fetchPermissions());
    //     }
    // }, [dispatch, permissions.length]);

    const handleTogglePerm = (code: string) => {
        setSelectedPerms(prev =>
            prev.includes(code) ? prev.filter(p => p !== code) : [...prev, code]
        );
    };

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        if (!name.trim()) {
            setError('Название роли обязательно');
            return;
        }
        if (selectedPerms.length === 0) {
            setError('Выберите хотя бы одно разрешение');
            return;
        }

        try {
            if (role) {
                await dispatch(updateRole({id: role.id, data: {name, permissions: selectedPerms as any}})).unwrap();
            } else {
                await dispatch(createRole({name, permissions: selectedPerms as any})).unwrap();
            }
            onClose();
        } catch (err: any) {
            setError(err?.message || 'Ошибка при сохранении роли');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()}
                 style={{maxWidth: '600px', maxHeight: '90vh', overflowY: 'auto'}}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{role ? 'Редактировать роль' : 'Создать роль'}</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <form onSubmit={handleSubmit}
                      style={{padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px'}}>
                    <input
                        className="modal_input"
                        placeholder="Название роли *"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        required
                    />

                    <div>
                        <label style={{fontSize: '14px', fontWeight: 'bold', marginBottom: '12px', display: 'block'}}>
                            Разрешения:
                        </label>
                        <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                            {permissions.map(p => (
                                <label key={p.code}
                                       style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer'}}>
                                    <input
                                        type="checkbox"
                                        checked={selectedPerms.includes(p.code)}
                                        onChange={() => handleTogglePerm(p.code)}
                                        style={{width: '16px', height: '16px'}}
                                    />
                                    <span style={{fontSize: '14px'}}>{p.title}</span>
                                </label>
                            ))}
                            {permissions.length === 0 &&
                                <span style={{color: 'var(--tpu-gray-text)'}}>Загрузка разрешений...</span>}
                        </div>
                    </div>

                    {error && <div style={{color: 'var(--danger)', fontSize: '14px'}}>{error}</div>}

                    <button type="submit" className="btn btn_primary" style={{marginTop: '16px'}}>
                        {role ? 'Сохранить изменения' : 'Создать роль'}
                    </button>
                </form>
            </div>
        </div>
    );
};