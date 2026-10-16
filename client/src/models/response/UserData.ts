export interface UserData {
    firstName: string;
    lastName: string;
    surname?: string;
    status: 'registered' | 'edited' | 'unregistered' | 'registeredWithoutLabel'
    post?: string;
    organization?: string;
    id: string;
    registrationDate: string | null;
    createdAt: string;
    marks?: string;
    registrationPlace: null | string
}