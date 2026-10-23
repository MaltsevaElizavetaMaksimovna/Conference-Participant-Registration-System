import axios, {type AxiosInstance} from 'axios';
import axiosRetry from 'axios-retry';

export const BASE_URL = '/api';

export function setupRetry(instance: AxiosInstance) {
    axiosRetry(instance, {
        retries: 3,
        retryDelay: axiosRetry.exponentialDelay,
        shouldResetTimeout: true,
        retryCondition: (error) => {
            const method = (error.config?.method ?? 'get').toLowerCase();
            const status = error.response?.status ?? 0;
            const hasIdempotencyKey = !!error.config?.headers?.['Idempotency-Key'];

            if (!error.response) return true; // сетевая

            if (status >= 500) {
                if (['get', 'head', 'put', 'patch'].includes(method)) return true;
                return hasIdempotencyKey;
            }

            return status === 429;

        },
        onRetry: (count, error, config) => {
            console.warn(`[api] retry ${count} for ${config.url}`, error.message);
        },
    });
}
