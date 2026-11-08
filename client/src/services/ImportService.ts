import {adminApi} from '~/api/adminApi';
import type {ImportAcceptedOut, ImportReportOut} from '~/models/api';
import type {AxiosResponse} from "axios";

export class ImportService {
    static async uploadFile(conferenceId: number, file: File): Promise<AxiosResponse<ImportAcceptedOut>> {
        const formData = new FormData();
        formData.append('file', file);
        return await adminApi.post<ImportAcceptedOut>(
            `/admin/conferences/${conferenceId}/imports`,
            formData
        );
    }

    static async getReport(conferenceId: number, batchId: number): Promise<AxiosResponse<ImportReportOut>> {
        return await adminApi.get<ImportReportOut>(
            `/admin/conferences/${conferenceId}/imports/${batchId}`
        );
    }

    static async downloadTemplate(): Promise<AxiosResponse<Blob>> {
        return await adminApi.get('/admin/import-template.xlsx', {
            responseType: 'blob',
        });
    }
}