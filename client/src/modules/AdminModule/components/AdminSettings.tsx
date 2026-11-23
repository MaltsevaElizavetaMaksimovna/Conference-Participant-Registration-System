import {useState, useEffect} from 'react';
import {Link, useSearchParams} from 'react-router';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {fetchConferences, activateConference} from '~/store/reducers/ConferenceSlice';
import {
    fetchTerminals,
    fetchPrinters,
    fetchUsers,
    fetchRoles,
    issueTerminalToken,
    blockUser,
    unblockUser,
    deleteRole,
    clearLastToken
} from '~/store/reducers/SettingsSlice';
import type {ConferenceOut, PrinterAdminOut, RoleOut, TerminalOut, UserOut} from '~/models/api';
import {CreateConferenceModal} from "~/modules/AdminModule/components/modals/CreateConferenceModal";
import {CreateTerminalModal} from "~/modules/AdminModule/components/modals/CreateTerminalModal";
import {CreatePrinterModal} from "~/modules/AdminModule/components/modals/CreatePrinterModal";
import {CreateUserModal} from "~/modules/AdminModule/components/modals/CreateUserModal";
import {RoleModal} from "~/modules/AdminModule/components/modals/RoleModal";
import {TerminalTokenModal} from "~/modules/AdminModule/components/modals/TerminalTokenModal";

import {settingsTabs, type SettingsTab} from './staffNavigation';
import {TemplateEditor} from './templates/TemplateEditor';
import {PrinterSettings} from './PrinterSettings';

export const AdminSettings = () => {
    const dispatch = useAppDispatch();
    const user = useAppSelector(state => state.authReducer.user);
    const [searchParams] = useSearchParams();
    const templateId = searchParams.get('templates') ?? '';
    const templateConferenceId = user?.permissions.includes(settingsTabs.conferences) && /^[1-9]\d*$/.test(templateId)
        && Number.isSafeInteger(Number(templateId)) ? Number(templateId) : null;
    const visibleTabs = (Object.keys(settingsTabs) as SettingsTab[]).filter(tab =>
        user?.permissions.includes(settingsTabs[tab]));
    const [chosenTab, setActiveTab] = useState<SettingsTab>('conferences');
    const activeTab = visibleTabs.includes(chosenTab) ? chosenTab : visibleTabs[0];

    const {list: conferences} = useAppSelector(state => state.conferenceReducer);
    const {terminals, printers, users, roles, lastIssuedToken} = useAppSelector(state => state.settingsReducer);

    const [conferenceModal, setConferenceModal] = useState<ConferenceOut | null>();
    const [terminalModal, setTerminalModal] = useState<TerminalOut | null>();
    const [printerModal, setPrinterModal] = useState<PrinterAdminOut | null>();
    const [userModal, setUserModal] = useState<UserOut | null>();
    const [isRoleModalOpen, setIsRoleModalOpen] = useState(false);
    const [editingRole, setEditingRole] = useState<RoleOut | null>(null);

    useEffect(() => {
        if (templateConferenceId !== null) return;
        if (activeTab === 'conferences') dispatch(fetchConferences({limit: 100, offset: 0}));
        if (activeTab === 'terminals') {
            dispatch(fetchTerminals());
            dispatch(fetchPrinters());
        }
        if (activeTab === 'users') {
            dispatch(fetchUsers());
            dispatch(fetchRoles());
        }
        if (activeTab === 'roles') dispatch(fetchRoles());
    }, [dispatch, activeTab, templateConferenceId]);

    const handleActivateConference = (id: number) => {
        if (window.confirm('Сделать эту конференцию активной? Терминалы переключатся на неё.')) {
            dispatch(activateConference(id));
        }
    };

    const handleIssueToken = async (id: number) => {
        if (window.confirm('Выдать новый токен? Предыдущий перестанет работать.')) {
            try {
                await dispatch(issueTerminalToken(id)).unwrap();
            } catch (e) {
                alert('Ошибка при выдаче токена');
            }
        }
    };

    const handleToggleBlock = (id: number, isBlocked: boolean) => {
        const action = isBlocked ? 'разблокировать' : 'заблокировать';
        if (window.confirm(`Вы уверены, что хотите ${action} сотрудника?`)) {
            if (isBlocked) {
                dispatch(unblockUser(id));
            } else {
                dispatch(blockUser(id));
            }
        }
    };

    const handleDeleteRole = (id: number, name: string) => {
        if (window.confirm(`Вы уверены, что хотите удалить роль "${name}"?`)) {
            dispatch(deleteRole(id)).unwrap().catch(() => {
                alert('Не удалось удалить роль. Возможно, она назначена сотрудникам.');
            });
        }
    };

    const openRoleModal = (role: RoleOut | null = null) => {
        setEditingRole(role);
        setIsRoleModalOpen(true);
    };

    const closeTokenModal = () => {
        dispatch(clearLastToken());
    };

    if (templateConferenceId !== null) {
        return <TemplateEditor key={templateConferenceId} conferenceId={templateConferenceId}/>;
    }

    return (
        <div className="admin_main admin_settings">
            <h1 style={{marginBottom: '24px'}}>Настройки системы</h1>

            <div style={{
                display: 'flex',
                gap: '8px',
                marginBottom: '24px',
                borderBottom: '1px solid var(--tpu-border)',
                paddingBottom: '16px'
            }}>
                {visibleTabs.map(tab => (
                    <button
                        key={tab}
                        className={`btn ${activeTab === tab ? 'btn_primary' : 'btn_secondary'}`}
                        style={{flex: 'none', padding: '8px 16px'}}
                        onClick={() => setActiveTab(tab)}
                    >
                        {tab === 'conferences' ? 'Конференции' :
                            tab === 'terminals' ? 'Терминалы и принтеры' :
                                tab === 'users' ? 'Сотрудники' : 'Роли'}
                    </button>
                ))}
            </div>

            {activeTab === 'conferences' && (
                <div>
                    <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '16px'
                    }}>
                        <h2>Список конференций</h2>
                        <button
                            className="btn btn_primary"
                            style={{flex: 'none', padding: '8px 16px'}}
                            onClick={() => setConferenceModal(null)}
                        >
                            + Создать конференцию
                        </button>
                    </div>
                    <div className="table_wrapper">
                        <table className="table">
                            <thead>
                            <tr>
                                <th>Название</th>
                                <th>Даты</th>
                                <th>Тип бейджа</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                            </thead>
                            <tbody>
                            {conferences.map(c => (
                                <tr key={c.id}>
                                    <td>{c.title}</td>
                                    <td>{c.date_from} — {c.date_to}</td>
                                    <td>
                                        {c.badge_type === 'single' ? 'Односторонний' :
                                            c.badge_type === 'double' ? 'Двусторонний' : 'Без бейджа'}
                                    </td>
                                    <td>
                                        {c.is_active
                                            ? <span className="badge badge_success">Активна</span>
                                            : <span className="badge badge_muted">Неактивна</span>
                                        }
                                    </td>
                                    <td>
                                        <div className="actions_cell">
                                            {!c.is_active && (
                                                <button
                                                    className="icon_btn"
                                                    onClick={() => handleActivateConference(c.id)}
                                                    style={{color: 'var(--tpu-green)', borderColor: 'var(--tpu-green)'}}
                                                >
                                                    Активировать
                                                </button>
                                            )}
                                            <Link className="icon_btn" to={`?templates=${c.id}`}>Шаблоны</Link>
                                            <button className="icon_btn" onClick={() => setConferenceModal(c)}>Изменить</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {conferences.length === 0 && (
                                <tr>
                                    <td colSpan={5} style={{textAlign: 'center'}}>Конференций пока нет</td>
                                </tr>
                            )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {activeTab === 'terminals' && (
                <div>
                    <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '16px'
                    }}>
                        <h2>Терминалы и Принтеры</h2>
                        <div style={{display: 'flex', gap: '8px'}}>
                            <button
                                className="btn btn_secondary"
                                style={{flex: 'none', padding: '8px 16px'}}
                                onClick={() => setPrinterModal(null)}
                            >
                                + Принтер
                            </button>
                            <button
                                className="btn btn_primary"
                                style={{flex: 'none', padding: '8px 16px'}}
                                onClick={() => setTerminalModal(null)}
                            >
                                + Терминал
                            </button>
                        </div>
                    </div>

                    <div className="table_wrapper">
                        <table className="table">
                            <thead>
                            <tr>
                                <th>Название терминала</th>
                                <th>Принтер</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                            </thead>
                            <tbody>
                            {terminals.map(t => {
                                const printer = printers.find(p => p.id === t.printer_id);
                                return (
                                    <tr key={t.id}>
                                        <td>{t.name}</td>
                                        <td>{printer ? printer.name : 'Не привязан'}</td>
                                        <td>
                                            {t.enabled
                                                ? <span className="badge badge_success">Включен</span>
                                                : <span className="badge badge_muted">Отключен</span>
                                            }
                                        </td>
                                        <td>
                                            <div className="actions_cell">
                                                <button className="icon_btn" onClick={() => setTerminalModal(t)}>Изменить</button>
                                                <button
                                                    className="icon_btn"
                                                    onClick={() => handleIssueToken(t.id)}
                                                    style={{color: 'var(--tpu-green)'}}
                                                >
                                                    Выдать токен
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                            {terminals.length === 0 && (
                                <tr>
                                    <td colSpan={4} style={{textAlign: 'center'}}>Терминалов пока нет</td>
                                </tr>
                            )}
                            </tbody>
                        </table>
                    </div>
                    <PrinterSettings printers={printers} onEdit={setPrinterModal}/>
                </div>
            )}

            {activeTab === 'users' && (
                <div>
                    <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '16px'
                    }}>
                        <h2>Сотрудники</h2>
                        <button
                            className="btn btn_primary"
                            style={{flex: 'none', padding: '8px 16px'}}
                            onClick={() => setUserModal(null)}
                        >
                            + Добавить сотрудника
                        </button>
                    </div>
                    <div className="table_wrapper">
                        <table className="table">
                            <thead>
                            <tr>
                                <th>ФИО</th>
                                <th>Логин</th>
                                <th>Роль</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                            </thead>
                            <tbody>
                            {users.map(u => (
                                <tr key={u.id}>
                                    <td>{u.full_name}</td>
                                    <td>{u.login}</td>
                                    <td>{u.role.name}</td>
                                    <td>
                                        {u.is_blocked
                                            ? <span className="badge badge_muted">Заблокирован</span>
                                            : <span className="badge badge_success">Активен</span>
                                        }
                                    </td>
                                    <td>
                                        <div className="actions_cell">
                                            <button
                                                className="icon_btn"
                                                onClick={() => handleToggleBlock(u.id, u.is_blocked)}
                                                style={{color: u.is_blocked ? 'var(--tpu-green)' : 'var(--danger)'}}
                                            >
                                                {u.is_blocked ? 'Разблокировать' : 'Блокировать'}
                                            </button>
                                            <button className="icon_btn" onClick={() => setUserModal(u)}>Изменить</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {users.length === 0 && (
                                <tr>
                                    <td colSpan={5} style={{textAlign: 'center'}}>Сотрудников пока нет</td>
                                </tr>
                            )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {activeTab === 'roles' && (
                <div>
                    <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '16px'
                    }}>
                        <h2>Роли и разрешения</h2>
                        <button
                            className="btn btn_primary"
                            style={{flex: 'none', padding: '8px 16px'}}
                            onClick={() => openRoleModal(null)}
                        >
                            + Создать роль
                        </button>
                    </div>
                    <div className="table_wrapper">
                        <table className="table">
                            <thead>
                            <tr>
                                <th>Название роли</th>
                                <th>Сотрудников</th>
                                <th>Разрешения</th>
                                <th>Действия</th>
                            </tr>
                            </thead>
                            <tbody>
                            {roles.map(r => (
                                <tr key={r.id}>
                                    <td>{r.name}</td>
                                    <td>{r.users_count}</td>
                                    <td>{r.permissions.length} шт.</td>
                                    <td>
                                        <div className="actions_cell">
                                            <button className="icon_btn" onClick={() => openRoleModal(r)}>Изменить
                                            </button>
                                            <button
                                                className="icon_btn"
                                                onClick={() => handleDeleteRole(r.id, r.name)}
                                                style={{color: 'var(--danger)'}}
                                            >
                                                Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {roles.length === 0 && (
                                <tr>
                                    <td colSpan={4} style={{textAlign: 'center'}}>Ролей пока нет</td>
                                </tr>
                            )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {conferenceModal !== undefined && <CreateConferenceModal conference={conferenceModal ?? undefined}
                onClose={() => setConferenceModal(undefined)}/>}
            {terminalModal !== undefined && <CreateTerminalModal terminal={terminalModal ?? undefined}
                onClose={() => setTerminalModal(undefined)}/>}
            {printerModal !== undefined && <CreatePrinterModal printer={printerModal ?? undefined}
                onClose={() => setPrinterModal(undefined)}/>}
            {userModal !== undefined && <CreateUserModal user={userModal ?? undefined} onClose={() => setUserModal(undefined)}/>}
            {isRoleModalOpen && <RoleModal role={editingRole} onClose={() => setIsRoleModalOpen(false)}/>}
            {lastIssuedToken && <TerminalTokenModal token={lastIssuedToken} onClose={closeTokenModal}/>}
        </div>
    );
};
