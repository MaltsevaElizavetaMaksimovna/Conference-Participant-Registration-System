import axios, { type InternalAxiosRequestConfig } from 'axios';
import {BASE_URL, setupRetry} from './config';

const TERMINAL_TOKEN_KEY = 'rs_terminal_token';

export function getTerminalToken(): string | null {
    return localStorage.getItem(TERMINAL_TOKEN_KEY);
}

export function setTerminalToken(token: string) {
    localStorage.setItem(TERMINAL_TOKEN_KEY, token);
}

export function clearTerminalToken() {
    localStorage.removeItem(TERMINAL_TOKEN_KEY);
}

export const terminalApi = axios.create({
    baseURL: BASE_URL,
    withCredentials: false,
    timeout: 15_000,
    headers: {
        Accept: 'application/json',
    }
})

setupRetry(terminalApi);

terminalApi.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = getTerminalToken();
    if (token) {
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Terminal ${token}`;
    }
    return config;
});
