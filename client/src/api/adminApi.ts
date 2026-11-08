import axios, {type AxiosError, type InternalAxiosRequestConfig} from "axios";
import {BASE_URL, setupRetry} from "~/api/config";

const CSRF_HEADER = 'X-Requested-With';
const CSRF_VALUE = 'rs';

export const adminApi = axios.create({
    baseURL: BASE_URL,
    withCredentials: true,
    timeout: 15_000,
    headers: {
        Accept: 'application/json',
    }
})

setupRetry(adminApi);

adminApi.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const method = (config.method ?? 'get').toLowerCase();
    if (!['get', 'head', 'options'].includes(method)) {
        config.headers = config.headers ?? {};
        config.headers[CSRF_HEADER] = CSRF_VALUE;
    }
    return config;
});

adminApi.interceptors.response.use(
    (res) => res,
    (error: AxiosError) => {
        if (error.response?.status === 401) {
            const url = error.config?.url ?? '';
            const isAuthEndpoint =
                url.includes('/auth/login') || url.includes('/auth/me');

            if (!isAuthEndpoint) {
                Promise.all([
                    import('~/store/store'),
                    import('~/store/reducers/AuthSlice'),
                ]).then(([{ store }, { logoutLocal }]) => {
                    store.dispatch(logoutLocal());
                });
            }
        }
        return Promise.reject(error);
    }
);