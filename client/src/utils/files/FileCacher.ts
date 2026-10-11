import type {CreateUserRequest} from "~/models/CreateUserRequest";

const cache = new Map<string, CreateUserRequest[]>();


export const makeCacheKey = (file: File) => {
    return `${file.name}-${file.size}-${file.lastModified}`
}

export const getCached = (key: string) => {
    return cache.get(key)
}

export const setCache = (key: string, value: CreateUserRequest[]) => {
    cache.set(key, value)
}

export const hasCached = (key: string) => {
    return cache.has(key)
}

const clearCache = () => {
    cache.clear()
}