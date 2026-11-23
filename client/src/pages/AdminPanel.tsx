import React, {useEffect, useState} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {logout} from '~/store/reducers/AuthSlice';
import {
    fetchParticipants,
    fetchParticipantsStats,
    setFilters,
    selectParticipant,
    clearSelected,
    fetchParticipantById,
    updateStatsFromSSE,
} from '~/store/reducers/AdminSlice';
import {useNavigate} from "react-router";
import {ParticipantCardModal} from "~/modules/AdminModule/components/modals/ParticipantCardModal";
import {AddParticipantModal} from "~/modules/AdminModule/components/modals/AddParticipantModal";
import {PanelPrinterSelect} from "~/modules/AdminModule/components/PanelPrinterSelect";
import {BASE_URL} from "~/api/config";
import {useStore} from "react-redux";
import type {RootState} from "~/store/store";


export const AdminPanel = () => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const store = useStore<RootState>();


    const {user, loginError} = useAppSelector(state => state.authReducer);
    const {participants, listStatus, listError, listTotal, filters, stats, selectedId} =
        useAppSelector(state => state.adminReducer);
    const conferenceId = useAppSelector(state => state.conferenceReducer.active?.id);
    const [isAddModalOpen, setIsAddModalOpen] = useState(false);
    const [reconnecting, setReconnecting] = useState(false);

    useEffect(() => {
        const request = dispatch(fetchParticipants(filters));
        return () => { request.abort(); };
    }, [dispatch, filters, conferenceId]);

    useEffect(() => {
        if (listStatus === 'success' && filters.offset > 0 && filters.offset >= listTotal) {
            dispatch(setFilters({offset: Math.max(0, Math.ceil(listTotal / filters.limit) - 1) * filters.limit}));
        }
    }, [dispatch, filters.limit, filters.offset, listStatus, listTotal]);

    useEffect(() => {
        const statsRequest = dispatch(fetchParticipantsStats());
        const events = new EventSource(BASE_URL + '/events/stream', {withCredentials: true});
        let refreshTimer: number | undefined;
        let listDirty = false;
        let cardDirty = false;

        function refresh() {
            refreshTimer = undefined;
            if (listDirty) dispatch(fetchParticipants());
            const {selectedId} = store.getState().adminReducer;
            if (cardDirty && selectedId !== null) dispatch(fetchParticipantById(selectedId));
            listDirty = false;
            cardDirty = false;
        }

        function scheduleRefresh(id?: number) {
            listDirty = true;
            if (id === undefined || id === store.getState().adminReducer.selectedId) cardDirty = true;
            if (refreshTimer === undefined) refreshTimer = window.setTimeout(refresh, 150);
        }

        events.onopen = () => {
            setReconnecting(false);
            scheduleRefresh();
        };
        events.onerror = () => setReconnecting(true);
        events.addEventListener('stats', event => {
            try {
                const stats = JSON.parse(event.data);
                if (Number.isInteger(stats.registered) && Number.isInteger(stats.total)) {
                    dispatch(updateStatsFromSSE(stats));
                }
            } catch { scheduleRefresh(); }
        });
        events.addEventListener('participant_updated', event => {
            try { scheduleRefresh(JSON.parse(event.data).id); }
            catch { scheduleRefresh(); }
        });
        return () => {
            events.close();
            window.clearTimeout(refreshTimer);
            statsRequest.abort();
            dispatch(clearSelected());
        };
    }, [dispatch, store, conferenceId]);

    const handleLogout = async () => {
        if (logout.fulfilled.match(await dispatch(logout()))) navigate('/login');
    };

    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        dispatch(setFilters({q: e.target.value, offset: 0}));
    };

    const handleFilterChange = (newFilter: typeof filters.filter) => {
        dispatch(setFilters({filter: newFilter, offset: 0}));
    };

    return (
        <>
            <main className="admin_main">
                <header className="admin_header">
                    <h1>Участники</h1>

                    <div style={{fontSize: '16px', fontWeight: 600, color: 'var(--tpu-green)'}}>
                        Зарегистрировано: {stats?.registered ?? "—"} из {stats?.total ?? "—"}
                    </div>

                    <div style={{display: 'flex', gap: '16px', alignItems: 'center'}}>
                        <span style={{fontSize: '14px', color: 'var(--tpu-gray-text)'}}>
                            {user?.full_name}
                        </span>
                        <button className="icon_btn" onClick={handleLogout}>Выйти</button>
                    </div>
                </header>

                {loginError && <p role="alert">{loginError.message}</p>}
                {reconnecting && <p role="status">Восстанавливаем связь с панелью…</p>}
                {user?.permissions.includes('stickers.print') && <PanelPrinterSelect/>}
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
                        disabled={!user?.permissions.includes("participants.add")}
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
                        {listStatus === 'error' && (
                            <tr><td colSpan={4} role="alert">
                                {listError?.message ?? 'Не удалось загрузить список'}{' '}
                                <button className="icon_btn" onClick={() => dispatch(fetchParticipants())}>Повторить</button>
                            </td></tr>
                        )}
                        {listStatus === 'loading' && (
                            <tr>
                                <td colSpan={4} style={{textAlign: 'center'}}>Загрузка...</td>
                            </tr>
                        )}

                        {listStatus === 'success' && participants.length === 0 && (
                            <tr>
                                <td colSpan={4} style={{textAlign: 'center'}}>Ничего не найдено</td>
                            </tr>
                        )}

                        {listStatus === 'success' && participants.map(p => (
                            <tr
                                key={p.id}
                                onClick={() => dispatch(selectParticipant(p.id))}
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
                {listTotal > filters.limit && (
                    <nav aria-label="Страницы участников" className="search_row">
                        <button className="btn btn_secondary" disabled={!filters.offset}
                                onClick={() => dispatch(setFilters({offset: Math.max(0, filters.offset - filters.limit)}))}>Назад</button>
                        <span>{filters.offset + 1}–{Math.min(filters.offset + filters.limit, listTotal)} из {listTotal}</span>
                        <button className="btn btn_secondary" disabled={filters.offset + filters.limit >= listTotal}
                                onClick={() => dispatch(setFilters({offset: filters.offset + filters.limit}))}>Далее</button>
                    </nav>
                )}
            </main>

            {selectedId !== null && <ParticipantCardModal key={selectedId}/>}
            {isAddModalOpen && <AddParticipantModal onClose={() => setIsAddModalOpen(false)}/>}
        </>
    );
};
