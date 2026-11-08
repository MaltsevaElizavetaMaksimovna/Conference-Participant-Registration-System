import { adminApi } from '~/api/adminApi';
import type {
    TerminalIn,
    TerminalOut,
    TerminalTokenOut,
    PrinterIn,
    PrinterAdminOut,
    PrinterTokenOut,
    UserCreateIn,
    UserUpdateIn,
    UserOut,
    RoleIn,
    RoleOut,
    PermissionOut, PageTerminalOut, PagePrinterAdminOut, PageUserOut, PageRoleOut
} from '~/models/api';
import type { AxiosResponse } from 'axios';

export class AdminService {
    static async listTerminals(): Promise<AxiosResponse<PageTerminalOut>> {
        return adminApi.get<PageTerminalOut>('/admin/terminals');
    }

    static async createTerminal(data: TerminalIn): Promise<AxiosResponse<TerminalOut>> {
        return adminApi.post<TerminalOut>('/admin/terminals', data);
    }

    static async updateTerminal(id: number, data: TerminalIn): Promise<AxiosResponse<TerminalOut>> {
        return adminApi.put<TerminalOut>(`/admin/terminals/${id}`, data);
    }

    static async issueTerminalToken(id: number): Promise<AxiosResponse<TerminalTokenOut>> {
        return adminApi.post<TerminalTokenOut>(`/admin/terminals/${id}/token`);
    }

    static async listPrinters(): Promise<AxiosResponse<PagePrinterAdminOut>> {
        return adminApi.get<PagePrinterAdminOut>('/admin/printers');
    }

    static async createPrinter(data: PrinterIn): Promise<AxiosResponse<PrinterAdminOut>> {
        return adminApi.post<PrinterAdminOut>('/admin/printers', data);
    }

    static async updatePrinter(id: number, data: PrinterIn): Promise<AxiosResponse<PrinterAdminOut>> {
        return adminApi.put<PrinterAdminOut>(`/admin/printers/${id}`, data);
    }

    static async issuePrinterToken(id: number): Promise<AxiosResponse<PrinterTokenOut>> {
        return adminApi.post<PrinterTokenOut>(`/admin/printers/${id}/token`);
    }

    static async listUsers(): Promise<AxiosResponse<PageUserOut>> {
        return adminApi.get<PageUserOut>('/admin/users');
    }

    static async createUser(data: UserCreateIn): Promise<AxiosResponse<UserOut>> {
        return adminApi.post<UserOut>('/admin/users', data);
    }

    static async updateUser(id: number, data: UserUpdateIn): Promise<AxiosResponse<UserOut>> {
        return adminApi.put<UserOut>(`/admin/users/${id}`, data);
    }

    static async blockUser(id: number): Promise<AxiosResponse<UserOut>> {
        return adminApi.post<UserOut>(`/admin/users/${id}/block`);
    }

    static async unblockUser(id: number): Promise<AxiosResponse<UserOut>> {
        return adminApi.post<UserOut>(`/admin/users/${id}/unblock`);
    }

    static async listRoles(): Promise<AxiosResponse<PageRoleOut>> {
        return adminApi.get<PageRoleOut>('/admin/roles');
    }

    static async createRole(data: RoleIn): Promise<AxiosResponse<RoleOut>> {
        return adminApi.post<RoleOut>('/admin/roles', data);
    }

    static async updateRole(id: number, data: RoleIn): Promise<AxiosResponse<RoleOut>> {
        return adminApi.put<RoleOut>(`/admin/roles/${id}`, data);
    }

    static async deleteRole(id: number): Promise<AxiosResponse<void>> {
        return adminApi.delete<void>(`/admin/roles/${id}`);
    }

    static async listPermissions(): Promise<AxiosResponse<PermissionOut[]>> {
        return adminApi.get<PermissionOut[]>('/admin/permissions');
    }
}