import { useEffect } from 'react';
import { Navigate, Outlet } from 'react-router';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import {fetchMe} from "~/store/reducers/AuthSlice";

export const RequireAuth = () => {
    const dispatch = useAppDispatch();
    const { status } = useAppSelector(state => state.authReducer);

    useEffect(() => {
        if (status === 'idle') {
            dispatch(fetchMe());
        }
    }, [dispatch, status]);

    if (status === 'idle' || status === 'loading') {
        return (
            <div className="terminal_container">
                <div className="terminal_spinner" />
                <p className="terminal_subtitle">Проверка авторизации...</p>
            </div>
        );
    }

    if (status === 'unauthenticated') {
        return <Navigate to="/login" replace />;
    }

    return <Outlet />;
};