import type {AxiosResponse} from "axios";
import type {
    ConfirmIn,
    ConfirmOut,
    PingOut, ReportErrorIn, ReportErrorOut,
    ScanAlreadyRegistered,
    ScanFound,
    ScanIn,
    ScanNotFound, TerminalPrintJobOut
} from "~/models/api";
import {terminalApi} from "~/api";

export type ScanResult = ScanFound | ScanNotFound | ScanAlreadyRegistered;

export class TerminalService {
    static async ping(): Promise<AxiosResponse<PingOut>> {
        return terminalApi.get<PingOut>('/terminal/ping');
    }

    static async scan(raw: string): Promise<AxiosResponse<ScanResult>> {
        const body: ScanIn = { raw };
        return terminalApi.post<ScanResult>('/terminal/scan', body);
    }

    static async confirm(data: ConfirmIn, idempotencyKey: string): Promise<AxiosResponse<ConfirmOut>> {
        return terminalApi.post<ConfirmOut>('/terminal/confirm', data, {
            headers: { 'Idempotency-Key': idempotencyKey },
        });
    }

    static async reportError(data: ReportErrorIn): Promise<AxiosResponse<ReportErrorOut>> {
        return terminalApi.post<ReportErrorOut>('/terminal/report-error', data);
    }

    static async getTerminalJob(id: number): Promise<AxiosResponse<TerminalPrintJobOut>> {
        return terminalApi.get<TerminalPrintJobOut>(`/terminal/print-jobs/${id}`);
    }
}