import type {MeOut} from '~/models/api';

export const settingsTabs = {
    conferences: 'conferences.manage',
    terminals: 'devices.manage',
    users: 'users.manage',
    roles: 'users.manage',
} as const;

export type SettingsTab = keyof typeof settingsTabs;

export function canOpenSettings(user: MeOut | null) {
    return Object.values(settingsTabs).some(permission => user?.permissions.includes(permission));
}
