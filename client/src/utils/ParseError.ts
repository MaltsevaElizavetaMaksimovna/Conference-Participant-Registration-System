import axios from "axios";
import type {Errors} from "~/models/Errors";


export function parseError(e: unknown): Errors {
    if (axios.isAxiosError(e)) {
        if (!e.response) {
            return {
                errorType: "networkError",
                message: 'Не удалось связаться с сервером',
                kind: 'system',
            }
        }
        const {status, data} = e.response
        const serverMessage = data?.message
        switch (status) {
            case 404:
                return {
                    errorType: 'userNotFound',
                    message: serverMessage ?? 'Пользователь не найден',
                    kind: 'business',
                    statusCode: status
                }
            case 409:
                return  {
                    errorType: 'alreadyRegistered',
                    message: serverMessage ?? 'Вы уже зарегистрированы',
                    kind: 'business',
                    statusCode: status
                }
            default:
                return {
                    errorType: "serverError",
                    statusCode: e.response.status,
                    message: e.response.data?.message ?? 'Ошибка сервера',
                    kind: 'system',
                }
        }
    }
    if (e instanceof Error) {
        return {
            message: e.message,
            errorType: 'unknownError',
            kind: 'system',
        }
    }
    return {
        message: 'Неизвестная ошибка',
        errorType: 'unknownError',
        kind: 'system',
    }
}