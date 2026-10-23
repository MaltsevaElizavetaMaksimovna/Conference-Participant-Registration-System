import type {
    CheckDuplicatesIn,
    DuplicatesOut,
    PageParticipantShort,
    ParticipantCard, ParticipantCreatedOut,
    ParticipantCreateIn,
    ParticipantStats,
    ParticipantUpdateIn
} from "~/models/api";
import type {AxiosResponse} from "axios";
import {adminApi} from "~/api";

export interface ParticipantListParams {
    q?: string;
    filter?: 'all' | 'registered' | 'not_registered' | 'flagged';
    sort?: 'name' | 'registered_at' | '-registered_at';
    limit?: number;
    offset?: number;
}

export class ParticipantService {
    static async list(params: ParticipantListParams = {}): Promise<AxiosResponse<PageParticipantShort>> {
        return adminApi.get<PageParticipantShort>('/participants', { params });
    }

    static async stats(): Promise<AxiosResponse<ParticipantStats>> {
        return adminApi.get<ParticipantStats>('/participants/stats');
    }

    static async getById(id: number): Promise<AxiosResponse<ParticipantCard>> {
        return adminApi.get<ParticipantCard>(`/participants/${id}`);
    }

    static async create(data: ParticipantCreateIn): Promise<AxiosResponse<ParticipantCreatedOut>> {
        return adminApi.post<ParticipantCreatedOut>('/participants', data);
    }

    static async update(id: number, data: ParticipantUpdateIn): Promise<AxiosResponse<ParticipantCard>> {
        return adminApi.patch<ParticipantCard>(`/participants/${id}`, data);
    }

    static async checkDuplicates(data: CheckDuplicatesIn): Promise<AxiosResponse<DuplicatesOut>> {
        return adminApi.post<DuplicatesOut>('/participants/check-duplicates', data);
    }
}