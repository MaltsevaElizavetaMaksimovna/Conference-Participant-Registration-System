
export interface CreateUserRequest {
    firstName: string;
    lastName: string;
    surname?: string;
    post?: string;
    organization?: string;
    status?: 'registered' | 'edited' | 'unregistered';
    marks?: string
    registrationPlace: null | string
}