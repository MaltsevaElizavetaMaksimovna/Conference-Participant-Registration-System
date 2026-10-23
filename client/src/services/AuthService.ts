import {adminApi} from "~/api";
import type {LoginIn, MeOut, PanelPrinterIn, PasswordChangeIn} from "~/models/api";
import type {AxiosResponse} from "axios";


export class AuthService {
    static async login(data: LoginIn): Promise<AxiosResponse<MeOut>> {
        return adminApi.post<MeOut>('/auth/login', data);
    }

    static async logout(): Promise<void> {
        return adminApi.post('/auth/logout');
    }

    static async fetchMe(): Promise<AxiosResponse<MeOut>> {
        return adminApi.get<MeOut>('/auth/me');
    }

    static async setPanelPrinter(printerId: number | null): Promise<AxiosResponse<MeOut>> {
        return adminApi.put<MeOut>('/auth/me/printer', {
            printer_id: printerId,
        } satisfies PanelPrinterIn);
    }

    static async changePassword(data: PasswordChangeIn): Promise<void> {
        return adminApi.put('/auth/me/password', data);
    }
}