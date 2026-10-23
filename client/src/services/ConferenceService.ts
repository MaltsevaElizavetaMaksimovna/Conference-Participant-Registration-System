import {adminApi} from "~/api/adminApi";
import type {ActiveConferenceOut, ConferenceIn, ConferenceOut, PageConferenceOut} from "~/models/api";
import type {AxiosResponse} from "axios";


export default class ConferenceService {
    static async getActive(): Promise<AxiosResponse<ActiveConferenceOut | null>> {
        return adminApi.get<ActiveConferenceOut | null>('/conferences/active');
    }

    static async list(limit = 50, offset = 0): Promise<AxiosResponse<PageConferenceOut>> {
        return adminApi.get<PageConferenceOut>('/admin/conferences', {
            params: {limit, offset},
        });
    }

    static async getById(id: number): Promise<AxiosResponse<ConferenceOut>> {
        return adminApi.get<ConferenceOut>(`/admin/conferences/${id}`);
    }

    static async create(data: ConferenceIn): Promise<AxiosResponse<ConferenceOut>> {
        return adminApi.post<ConferenceOut>('/admin/conferences', data);
    }

    static async update(id: number, data: ConferenceIn): Promise<AxiosResponse<ConferenceOut>> {
        return adminApi.put<ConferenceOut>(`/admin/conferences/${id}`, data);
    }

    static async activate(id: number): Promise<AxiosResponse<ConferenceOut>> {
        return adminApi.post<ConferenceOut>(`/admin/conferences/${id}/activate`);
    }
}