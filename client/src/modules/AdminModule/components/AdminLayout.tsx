import {useEffect} from 'react';
import {Link, Navigate, Outlet, useLocation} from 'react-router';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {fetchActiveConference} from '~/store/reducers/ConferenceSlice';
import {canOpenSettings} from './staffNavigation';

export const AdminLayout = () => {
    const dispatch = useAppDispatch();
    const {pathname} = useLocation();
    const user = useAppSelector(state => state.authReducer.user);

    useEffect(() => {
        dispatch(fetchActiveConference());
    }, [dispatch, user?.id]);

    const pages = [
        {path: '/admin', title: 'Участники', visible: user?.permissions.includes('participants.view')},
        {path: '/admin/import', title: 'Импорт данных', visible: user?.permissions.includes('imports.run')},
        {path: '/admin/settings', title: 'Настройки', visible: canOpenSettings(user)},
    ].filter(page => page.visible);

    if (!pages.length) {
        return <main className="admin_main"><p>Нет доступных разделов панели.</p><Link to="/login">Войти под другой учётной записью</Link></main>;
    }
    const currentPath = pathname.replace(/\/$/, '');
    if (!pages.some(page => page.path === currentPath)) {
        return <Navigate to={pages[0].path} replace/>;
    }
    return (
        <div className="admin_layout">
            <aside className="admin_sidebar">
                <div className="admin_logo">ТПУ · Регистрация</div>
                {pages.map(page => (
                    <Link key={page.path} to={page.path}
                          className={`nav_item ${currentPath === page.path ? 'active' : ''}`}>
                        {page.title}
                    </Link>
                ))}
            </aside>
            <Outlet/>
        </div>
    );
};
