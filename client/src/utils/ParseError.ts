import type {Errors} from "~/models/Errors";
import axios from "axios";


export function parseError(e: unknown): Errors {
    if (axios.isAxiosError(e)) {
        if (e.code === 'ERR_CANCELED') {
            return {errorType: 'canceled', kind: 'business', message: 'Запрос отменён'};
        }

        if (!e.response) {
            if (e.code === 'ECONNABORTED') {
                return {errorType: 'timeout', kind: 'system', message: 'Сервер не отвечает'};
            }
            return {errorType: 'networkError', kind: 'system', message: 'Нет связи с сервером'};
        }

        const {status, data} = e.response;
        const code: string = data?.code ?? 'unknown';
        const message: string = data?.message ?? 'Неизвестная ошибка';

        switch (code) {
            case 'unauthenticated':
                return {errorType: 'unauthorized', kind: 'system', statusCode: 401, message, code};
            case 'csrf_required':
                return {errorType: 'unknownError', kind: 'system', statusCode: 403, message, code};
            case 'forbidden':
                return {errorType: 'forbidden', kind: 'business', statusCode: 403, message, code};
            case 'invalid_credentials':
                return {errorType: 'invalidCredentials', kind: 'business', statusCode: 401, message, code};
            case 'user_blocked':
                return {errorType: 'userBlocked', kind: 'business', statusCode: 403, message, code};
            case 'too_many_requests':
                return {errorType: 'rateLimited', kind: 'system', statusCode: 429, message, code};
            case 'validation_error':
                return {
                    errorType: 'validationError',
                    kind: 'business',
                    statusCode: 422,
                    message,
                    code,
                    details: data?.details
                };
            case 'already_registered':
                return {
                    errorType: 'alreadyRegistered',
                    kind: 'business',
                    statusCode: 409,
                    message,
                    code,
                    details: data?.details
                };
            case 'participant_not_found':
                return {errorType: 'userNotFound', kind: 'business', statusCode: 404, message, code};
            case 'scan_expired':
                return {errorType: 'scanExpired', kind: 'business', statusCode: 409, message, code};
            case 'terminal_disabled':
                return {errorType: 'terminalDisabled', kind: 'system', statusCode: 423, message, code};
            case 'invalid_device_token':
                return {errorType: 'invalidDeviceToken', kind: 'system', statusCode: 401, message, code};
            case 'not_registered':
                return {errorType: 'notRegistered', kind: 'business', statusCode: 409, message, code};
            case 'photo_not_found':
                return {errorType: 'photoNotFound', kind: 'business', statusCode: 404, message, code};
            case 'profile_not_found':
                return {errorType: 'profileNotFound', kind: 'business', statusCode: 404, message, code};
            case 'internal_error':
                return {errorType: 'serverError', kind: 'system', statusCode: 500, message, code};
        }

        if (status >= 500) {
            return {errorType: 'serverError', kind: 'system', statusCode: status, message, code};
        }
        return {errorType: 'unknownError', kind: 'system', statusCode: status, message, code};
    }

    if (e instanceof Error) {
        return {errorType: 'unknownError', kind: 'system', message: e.message};
    }

    return {errorType: 'unknownError', kind: 'system', message: 'Неизвестная ошибка'};
}