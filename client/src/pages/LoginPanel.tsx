import React, { useState } from 'react';
import { useNavigate } from 'react-router';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import { login } from '~/store/reducers/AuthSlice';

export const LoginPanel = () => {
    const [loginValue, setLoginValue] = useState('');
    const [password, setPassword] = useState('');
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const { status, loginError } = useAppSelector(state => state.authReducer);

    const handleSubmit = async (e: React.SubmitEvent) => {
        e.preventDefault();
        const result = await dispatch(login({ login: loginValue, password }));
        if (login.fulfilled.match(result)) {
            navigate('/admin');
        }
    };

    return (
        <div className="terminal_container">
            <div className="terminal_content" style={{ maxWidth: '400px' }}>
                <h1 className="terminal_title">Вход в панель</h1>

                <form onSubmit={handleSubmit} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <input
                        className="input"
                        placeholder="Логин"
                        value={loginValue}
                        onChange={(e) => setLoginValue(e.target.value)}
                        required
                    />
                    <input
                        className="input"
                        type="password"
                        placeholder="Пароль"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                    />

                    {loginError && (
                        <div style={{ color: 'var(--danger)', fontSize: '14px' }}>
                            {loginError.message}
                        </div>
                    )}

                    <button
                        type="submit"
                        className="btn btn_primary"
                        disabled={status === 'loading'}
                    >
                        {status === 'loading' ? 'Вход...' : 'Войти'}
                    </button>
                </form>
            </div>
        </div>
    );
};