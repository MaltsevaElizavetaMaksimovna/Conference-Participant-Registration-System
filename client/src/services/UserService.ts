import type {UserData} from "~/models/UserData";
import type {AxiosResponse} from "axios";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import {adminApi} from "~/api";


export default class UserService {
    static async findUser(token: string): Promise<AxiosResponse<UserData>> {
        return adminApi.post<UserData>(`/users/find`, {token}, {})
    }
    static async completeRegistration(userId: string): Promise<AxiosResponse<UserData>> {
        return adminApi.post<UserData>(`users/${userId}/register`, {}, {})
    }
    static async manualRegister(userId: string): Promise<AxiosResponse<UserData>> {
        return adminApi.post<UserData>(`users/${userId}/manual-register`, {})
    }

    static async updateUser(userId: string, patch: UserData): Promise<AxiosResponse<UserData>> {
        return  adminApi.patch(`users/${userId}`, patch)
    }

    static async addUser(data: CreateUserRequest): Promise<AxiosResponse<UserData>> {
        return adminApi.post<UserData>('/users/add', data, {})
    }

    static async fillUsersList(data: CreateUserRequest[]): Promise<AxiosResponse<UserData[]>> {
        return adminApi.post<UserData[]>('/users/addFromFile', data, {})
    }

    static async getUsers(): Promise<AxiosResponse<UserData[]>> {
        return adminApi.get<UserData[]>('/users/getUsers', {});
    }

    static async markUserWithoutBadge(id: string): Promise<AxiosResponse<void>> {
        return adminApi.patch<void>(`users/${id}/mark`, {})
    }
}