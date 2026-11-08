import type {AxiosResponse} from "axios";
import {adminApi} from "~/api";
import type {PrinterOut, PrintJobOut, PrintJobRefOut, RegisterIn, RegisterOut} from "~/models/api";


export class DeskService {
    static async register(id: number, data: RegisterIn): Promise<AxiosResponse<RegisterOut>> {
        return adminApi.post<RegisterOut>(`/participants/${id}/register`, data);
    }

    static async reprint(id: number): Promise<AxiosResponse<PrintJobRefOut>> {
        return adminApi.post<PrintJobRefOut>(`/participants/${id}/reprint`);
    }

    static async foreignCode(id: number): Promise<AxiosResponse<PrintJobRefOut>> {
        return adminApi.post<PrintJobRefOut>(`/participants/${id}/foreign-code`);
    }

    static async getPrintJob(id: number): Promise<AxiosResponse<PrintJobOut>> {
        return adminApi.get<PrintJobOut>(`/print-jobs/${id}`);
    }

    static async listPrinters(): Promise<AxiosResponse<PrinterOut[]>> {
        return adminApi.get<PrinterOut[]>('/printers');
    }
}