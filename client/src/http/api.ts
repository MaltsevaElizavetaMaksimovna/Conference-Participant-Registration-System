import axios from "axios";
import axiosRetry from "axios-retry";


const $api = axios.create({
    baseURL: 'http://localhost:3000',
    withCredentials: true,
})

axiosRetry($api, {
    retries: 3,
    retryDelay: axiosRetry.exponentialDelay,
    shouldResetTimeout: true,
    retryCondition: (error) => {
        const method = error.config?.method?.toLowerCase() ?? ''
        const status = error.response?.status ?? 0

        const  isIdempotent = ['get', 'patch', 'put', 'head'].includes(method)
        if (!isIdempotent) return false

        return !error.response || status >= 500
    },
    onRetry: (retryCount, error, requestConfig) => {
        console.warn(`api retry ${retryCount} for ${requestConfig.url}`, error.message)
    }
})

export default $api