import $api from "~/http/api";
import type {AxiosResponse} from "axios";
import type {Conference, ConferenceTemplates} from "~/store/reducers/ConferenceSlice";


export default class ConferenceService {
    static async getSettings(): Promise<AxiosResponse<Conference>> {
        return $api.get<Conference>('/conferences/getSettings', {});
    }

    static async getTemplates(conferenceId: string): Promise<AxiosResponse<ConferenceTemplates>>{
        return $api.get<ConferenceTemplates>(`/conferences/${conferenceId}/templates`, {});
    }

    static async updateSettings(patch: Partial<Conference>): Promise<AxiosResponse<Conference>> {
        return $api.patch<Conference>('/conferences/patch', patch, {});
    }
}