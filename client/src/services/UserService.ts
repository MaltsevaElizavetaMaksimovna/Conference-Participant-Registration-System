import $api from "~/http/api";
import type {UserData} from "~/models/UserData";
import type {AxiosResponse} from "axios";
import type {CreateUserRequest} from "~/models/CreateUserRequest";


export default class UserService {
    static async findUser(token: string): Promise<AxiosResponse<UserData>> {
        return $api.post<UserData>(`/users/find`, {token}, {})
    }
    static async completeRegistration(userId: string): Promise<AxiosResponse<UserData>> {
        return $api.post<UserData>(`users/${userId}/register`, {}, {})
    }
    static async manualRegister(userId: string): Promise<AxiosResponse<UserData>> {
        return $api.post<UserData>(`users/${userId}/manual-register`, {})
    }

    static async updateUser(userId: string, patch: UserData): Promise<AxiosResponse<UserData>> {
        return  $api.patch(`users/${userId}`, patch)
    }

    static async addUser(data: CreateUserRequest): Promise<AxiosResponse<UserData>> {
        return $api.post<UserData>('/users/add', data, {})
    }

    static async fillUsersList(data: CreateUserRequest[]): Promise<AxiosResponse<UserData[]>> {
        return $api.post<UserData[]>('/users/addFromFile', data, {})
    }

    static async getUsers(): Promise<AxiosResponse<UserData[]>> {
        return $api.get<UserData[]>('/users/getUsers', {});
    }

    static async markUserWithoutBadge(id: string): Promise<AxiosResponse<void>> {
        return $api.patch<void>(`users/${id}/mark`, {})
    }
}