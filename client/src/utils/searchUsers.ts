import type {UserData} from "~/models/UserData";
import {normalizeYo} from "~/utils/NormalizeYo";


export const searchUsers = (users: UserData[], query: string) => {
    if (!query) return users

    const normalizedQuery = normalizeYo(query)
    if (normalizedQuery.length < 2) return users
    const words = normalizedQuery.split(/\s+/)

    return users.filter(user => {
        const fullName = normalizeYo(`${user.lastName} ${user.firstName} ${user.surname || ''}`.toLowerCase());
        return words.every((word) => fullName.includes(word));
    })
}