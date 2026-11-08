import {useEffect} from 'react';
import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {logout} from '~/store/reducers/AuthSlice';
import {fetchActiveConference} from '~/store/reducers/ConferenceSlice';
import {Outlet, useLocation, useNavigate} from "react-router";

export const AdminLayout = () => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const location = useLocation();
    const user = useAppSelector(state => state.authReducer.user);

    const {activeStatus} = useAppSelector(state => state.conferenceReducer);

    useEffect(() => {
        if (activeStatus === 'idle') {
            dispatch(fetchActiveConference());
        }
    }, [dispatch, activeStatus]);

    const handleLogout = async () => {
        await dispatch(logout());
        navigate('/login');
    };

    return (
        <div className="admin_layout">
            <aside className="admin_sidebar">
                <div className="admin_logo">ТПУ · Регистрация</div>

                <div
                    className={`nav_item ${location.pathname === '/admin' ? 'active' : ''}`}
                    onClick={() => navigate('/admin')}
                >
                    Участники
                </div>

                <div
                    className={`nav_item ${location.pathname === '/admin/import' ? 'active' : ''}`}
                    onClick={() => navigate('/admin/import')}
                >
                    Импорт данных
                </div>

                <div
                    className={`nav_item ${location.pathname === '/admin/settings' ? 'active' : ''}`}
                    onClick={() => navigate('/admin/settings')}
                >
                    Настройки
                </div>
            </aside>
            <Outlet/>
        </div>
    );
};