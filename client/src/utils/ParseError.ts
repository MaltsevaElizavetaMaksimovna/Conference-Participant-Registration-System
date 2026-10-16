import axios from "axios";
import type {Errors} from "~/models/response/Errors";


export function parseError(e: unknown): Errors {
    if (axios.isAxiosError(e)) {
        if (!e.response) {
            return {
                errorType: "networkError",
                message: 'Не удалось связаться с сервером',
                isBusinessError: false,
            }
        }
        const {status, data} = e.response
        const serverMessage = data?.message
        switch (status) {
            case 404:
                return {
                    errorType: 'userNotFound',
                    message: serverMessage ?? 'Пользователь не найден',
                    isBusinessError: true,
                }
            default:
                return {
                    errorType: "serverError",
                    statusCode: e.response.status,
                    message: e.response.data?.message ?? 'Ошибка сервера',
                    isBusinessError: false,
                }
        }
    }
    if (e instanceof Error) {
        return {
            message: e.message,
            errorType: 'unknownError',
            isBusinessError: false,
        }
    }
    return {
        message: 'Неизвестная ошибка',
        errorType: 'unknownError',
        isBusinessError: false,
    }
}