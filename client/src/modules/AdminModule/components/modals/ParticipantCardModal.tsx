import {useEffect, useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {
    fetchParticipantById,
    clearSelected,
    reprintSticker,
    foreignCode,
    updateParticipant, registerParticipantFromDesk,
} from '~/store/reducers/AdminSlice';

export const ParticipantCardModal = () => {
    const dispatch = useAppDispatch();
    const {selected: participant} = useAppSelector(state => state.adminReducer);

    const selectedStatus = useAppSelector(state => state.adminReducer.selectedStatus);

    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({
        last_name: '',
        first_name: '',
        middle_name: '',
        position: '',
        organization: '',
    });

    // Запрос полных данных
    useEffect(() => {
        if (participant?.id) {
            dispatch(fetchParticipantById(participant.id));
        }
    }, [dispatch, participant?.id]);

    // Синхронизация формы при загрузке данных
    useEffect(() => {
        if (participant) {
            setFormData({
                last_name: participant.last_name || '',
                first_name: participant.first_name || '',
                middle_name: participant.middle_name || '',
                position: participant.position || '',
                organization: participant.organization || '',
            });
        }
    }, [participant]);

    if (!participant) return null;

    if (selectedStatus === 'loading' || !participant.actions) {
        return (
            <div className="add_user_modal_container" onClick={() => dispatch(clearSelected())}>
                <div className="add_user_modal" onClick={e => e.stopPropagation()}
                     style={{padding: '40px', textAlign: 'center'}}>
                    <div className="terminal_spinner" style={{margin: '0 auto 20px'}}/>
                    <p>Загрузка карточки участника...</p>
                </div>
            </div>
        );
    }

    const {actions, status, registration, history, print_count, rescan_count, flags} = participant;

    const handleRegister = (withSticker: boolean) => {
        dispatch(registerParticipantFromDesk({id: participant.id, data: {with_sticker: withSticker}}));
    };

    const handleSaveEdit = () => {
        dispatch(updateParticipant({id: participant.id, data: formData}));
        setIsEditing(false);
    };

    return (
        <div className="add_user_modal_container" onClick={() => dispatch(clearSelected())}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()}
                 style={{maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto'}}>

                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Карточка участника</h2>
                    <button className="icon_btn" onClick={() => dispatch(clearSelected())}>✖</button>
                </div>

                <div style={{padding: '24px'}}>
                    <div style={{display: 'flex', gap: '24px', marginBottom: '24px'}}>
                        {participant.photo_url ? (
                            <img src={`http://localhost:8000${participant.photo_url}`} alt="Фото"
                                 style={{width: '120px', height: '160px', objectFit: 'cover', borderRadius: '8px'}}/>
                        ) : (
                            <div style={{
                                width: '120px',
                                height: '160px',
                                background: 'var(--tpu-gray-bg)',
                                borderRadius: '8px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: '12px',
                                color: 'var(--tpu-gray-text)',
                                textAlign: 'center'
                            }}>
                                Нет фото
                            </div>
                        )}

                        <div style={{flex: 1}}>
                            {isEditing ? (
                                <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                                    <input className="modal_input" value={formData.last_name}
                                           onChange={e => setFormData({...formData, last_name: e.target.value})}
                                           placeholder="Фамилия"/>
                                    <input className="modal_input" value={formData.first_name}
                                           onChange={e => setFormData({...formData, first_name: e.target.value})}
                                           placeholder="Имя"/>
                                    <input className="modal_input" value={formData.middle_name}
                                           onChange={e => setFormData({...formData, middle_name: e.target.value})}
                                           placeholder="Отчество"/>
                                    <input className="modal_input" value={formData.position}
                                           onChange={e => setFormData({...formData, position: e.target.value})}
                                           placeholder="Должность"/>
                                    <input className="modal_input" value={formData.organization}
                                           onChange={e => setFormData({...formData, organization: e.target.value})}
                                           placeholder="Организация"/>
                                </div>
                            ) : (
                                <>
                                    <h3 style={{marginBottom: '8px', fontSize: '22px'}}>
                                        {[participant.last_name, participant.first_name, participant.middle_name].filter(Boolean).join(' ')}
                                    </h3>
                                    <p style={{
                                        color: 'var(--tpu-gray-text)',
                                        marginBottom: '4px'
                                    }}>{participant.position || 'Должность не указана'}</p>
                                    <p style={{
                                        color: 'var(--tpu-gray-text)',
                                        marginBottom: '16px'
                                    }}>{participant.organization || 'Организация не указана'}</p>
                                    <span className={`badge ${
                                        status === 'registered' ? 'badge_success' :
                                            status === 'registered_no_sticker' ? 'badge_warn' : 'badge_muted'
                                    }`}>
                                        {status === 'registered' ? 'Зарегистрирован' :
                                            status === 'registered_no_sticker' ? 'Зарегистрирован (без наклейки)' : 'Не зарегистрирован'}
                                    </span>
                                </>
                            )}
                        </div>
                    </div>

                    {registration && (
                        <div style={{
                            padding: '12px',
                            background: 'var(--tpu-gray-bg)',
                            borderRadius: '6px',
                            fontSize: '14px',
                            marginBottom: '24px'
                        }}>
                            <strong>Регистрация:</strong> {new Date(registration.at).toLocaleString('ru-RU')} <br/>
                            <strong>Место:</strong> {registration.source === 'terminal' ? registration.terminal_name : `Стойка (${registration.user_login})`}
                        </div>
                    )}

                    {/* Флаги (пометки) */}
                    {flags.length > 0 && (
                        <div style={{marginBottom: '24px'}}>
                            <strong style={{display: 'block', marginBottom: '8px'}}>Пометки:</strong>
                            <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
                                {flags.map(f => (
                                    <span key={f.code} className="badge badge_warn">
                                        {f.code === 'data_changed' ? 'Данные изменены' :
                                            f.code === 'manual_added' ? 'Добавлен вручную' :
                                                f.code === 'foreign_code' ? 'Чужой код' :
                                                    f.code === 'sticker_not_printed' ? 'Наклейка не напечатана' :
                                                        f.code === 'error_reported' ? 'Сообщил об ошибке' : f.code}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    <div style={{
                        display: 'flex',
                        gap: '12px',
                        flexWrap: 'wrap',
                        marginBottom: '24px',
                        paddingBottom: '24px',
                        borderBottom: '1px solid var(--tpu-border)'
                    }}>
                        {isEditing ? (
                            <>
                                <button className="btn btn_primary" onClick={handleSaveEdit}>Сохранить</button>
                                <button className="btn btn_secondary" onClick={() => setIsEditing(false)}>Отмена
                                </button>
                            </>
                        ) : (
                            <>
                                {actions.can_edit && (
                                    <button className="btn btn_secondary"
                                            onClick={() => setIsEditing(true)}>Редактировать</button>
                                )}
                                {actions.can_register && (
                                    <>
                                        <button className="btn btn_primary"
                                                onClick={() => handleRegister(true)}>Зарегистрировать (с наклейкой)
                                        </button>
                                        <button className="btn btn_secondary"
                                                onClick={() => handleRegister(false)}>Зарегистрировать (без наклейки)
                                        </button>
                                    </>
                                )}
                                {actions.can_reprint && (
                                    <button className="btn btn_secondary"
                                            onClick={() => dispatch(reprintSticker(participant.id))}>Напечатать
                                        повторно</button>
                                )}
                                {actions.can_foreign_code && (
                                    <button className="btn btn_danger" onClick={() => {
                                        if (window.confirm('Вы уверены, что хотите зарегистрировать по чужому коду? Старая наклейка будет аннулирована.')) {
                                            dispatch(foreignCode(participant.id));
                                        }
                                    }}>Чужой код</button>
                                )}
                            </>
                        )}
                    </div>

                    <div>
                        <strong style={{display: 'block', marginBottom: '12px', fontSize: '16px'}}>История
                            изменений</strong>
                        {history.length === 0 ? (
                            <p style={{color: 'var(--tpu-gray-text)', fontSize: '14px'}}>Изменений нет</p>
                        ) : (
                            <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                                {history.map((h, i) => (
                                    <div key={i} style={{
                                        fontSize: '14px',
                                        background: 'var(--tpu-gray-bg)',
                                        padding: '8px 12px',
                                        borderRadius: '4px'
                                    }}>
                                        <span
                                            style={{color: 'var(--tpu-gray-text)'}}>{new Date(h.at).toLocaleString('ru-RU')}</span> —
                                        <strong> {h.field}</strong>: {h.old || '—'} → {h.new}
                                        {h.user_login &&
                                            <span style={{color: 'var(--tpu-gray-text)'}}> ({h.user_login})</span>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};