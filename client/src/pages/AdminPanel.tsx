import React, {useEffect, useMemo, useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {logout} from '~/store/reducers/AuthSlice';
import {
    fetchParticipants,
    fetchParticipantsStats,
    setFilters,
    setSelected,
} from '~/store/reducers/AdminSlice';
import {useNavigate} from "react-router";
import {normalizeYo} from "~/utils/NormalizeYo";
import {ParticipantCardModal} from "~/modules/AdminModule/components/modals/ParticipantCardModal";
import {AddParticipantModal} from "~/modules/AdminModule/components/modals/AddParticipantModal";


export const AdminPanel = () => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();

    const user = useAppSelector(state => state.authReducer.user);
    const {participants, listStatus, filters, stats} = useAppSelector(state => state.adminReducer);

    const selectedParticipant = useAppSelector(state => state.adminReducer.selected);
    const actionStatus = useAppSelector(state => state.adminReducer.actionStatus);

    const [isAddModalOpen, setIsAddModalOpen] = useState(false);

    // useEffect(() => {
    //     dispatch(fetchParticipants());
    //     dispatch(fetchParticipantsStats());
    // }, [dispatch, filters]);
    //
    // useEffect(() => {
    //     if (actionStatus === 'success') {
    //         dispatch(fetchParticipantsStats());
    //         dispatch(fetchParticipants());
    //     }
    // }, [actionStatus, dispatch]);

    const handleLogout = async () => {
        await dispatch(logout());
        navigate('/login');
    };

    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        dispatch(setFilters({q: e.target.value, offset: 0}));
    };

    const handleFilterChange = (newFilter: typeof filters.filter) => {
        dispatch(setFilters({filter: newFilter, offset: 0}));
    };

    const displayedParticipants = useMemo(() => {
        if (!filters.q) return participants;
        const query = normalizeYo(filters.q);
        return participants.filter(p => normalizeYo(p.full_name).includes(query));
    }, [participants, filters.q]);

    return (
        <div className="admin_layout">
            <aside className="admin_sidebar">
                <div className="admin_logo">ТПУ · Регистрация</div>
                <div className="nav_item active">Участники</div>
                {/* Остальные вкладки можно добавить позже */}
            </aside>

            <main className="admin_main">
                <header className="admin_header">
                    <h1>Участники</h1>

                    <div style={{fontSize: '16px', fontWeight: 600, color: 'var(--tpu-green)'}}>
                        Зарегистрировано: {stats?.registered || 0} из {stats?.total || 0}
                    </div>

                    <div style={{display: 'flex', gap: '16px', alignItems: 'center'}}>
                        <span style={{fontSize: '14px', color: 'var(--tpu-gray-text)'}}>
                            {user?.full_name}
                        </span>
                        <button className="icon_btn" onClick={handleLogout}>Выйти</button>
                    </div>
                </header>

                <div className="search_row">
                    <input
                        className="input"
                        placeholder="Поиск по ФИО..."
                        value={filters.q}
                        onChange={handleSearch}
                    />
                    <button
                        className="btn btn_primary"
                        style={{flex: 'none', padding: '0 24px'}}
                        onClick={() => setIsAddModalOpen(true)}
                    >
                        + Добавить вручную
                    </button>
                </div>

                <div className="search_row" style={{marginBottom: '16px'}}>
                    {(['all', 'registered', 'not_registered', 'flagged'] as const).map(f => (
                        <button
                            key={f}
                            className={`btn ${filters.filter === f ? 'btn_primary' : 'btn_secondary'}`}
                            style={{flex: 'none', padding: '8px 16px', fontSize: '14px'}}
                            onClick={() => handleFilterChange(f)}
                        >
                            {f === 'all' ? 'Все' :
                                f === 'registered' ? 'Зарегистрированы' :
                                    f === 'not_registered' ? 'Не пришли' : 'С пометками'}
                        </button>
                    ))}
                </div>

                <div className="table_wrapper">
                    <table className="table">
                        <thead>
                        <tr>
                            <th>ФИО</th>
                            <th>Организация</th>
                            <th>Статус</th>
                            <th>Пометки</th>
                        </tr>
                        </thead>
                        <tbody>
                        {listStatus === 'loading' && (
                            <tr>
                                <td colSpan={4} style={{textAlign: 'center'}}>Загрузка...</td>
                            </tr>
                        )}

                        {listStatus === 'success' && displayedParticipants.length === 0 && (
                            <tr>
                                <td colSpan={4} style={{textAlign: 'center'}}>Ничего не найдено</td>
                            </tr>
                        )}

                        {listStatus === 'success' && displayedParticipants.map(p => (
                            <tr
                                key={p.id}
                                onClick={() => dispatch(setSelected(p as any))}
                                style={{cursor: 'pointer'}}
                                className="table_row_hover"
                            >
                                <td>{p.full_name}</td>
                                <td>{p.organization || '—'}</td>
                                <td>
                                        <span className={`badge ${
                                            p.status === 'registered' ? 'badge_success' :
                                                p.status === 'registered_no_sticker' ? 'badge_warn' : 'badge_muted'
                                        }`}>
                                            {p.status === 'registered' ? 'Зарегистрирован' :
                                                p.status === 'registered_no_sticker' ? 'Без наклейки' : 'Не пришел'}
                                        </span>
                                </td>
                                <td>
                                    {p.flags.map(flag => (
                                        <span key={flag} className="badge badge_warn"
                                              style={{marginRight: '4px', fontSize: '11px'}}>
                                                {flag}
                                            </span>
                                    ))}
                                </td>
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </div>
            </main>

            {selectedParticipant && <ParticipantCardModal/>}
            {isAddModalOpen && <AddParticipantModal onClose={() => setIsAddModalOpen(false)}/>}
        </div>
    );
};