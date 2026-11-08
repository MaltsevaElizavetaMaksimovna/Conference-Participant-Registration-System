export type ErrorKind = 'system' | 'business'

export type ErrorTypes =
    'userNotFound'
    | 'alreadyRegistered'
    | 'networkError'
    | 'uncorrectedData'
    | 'serverError'
    | 'unknownError'
    | 'printError'
    | 'canceled'
    | 'unauthorized'
    | 'forbidden'
    | 'invalidCredentials'
    | 'userBlocked'
    | 'timeout'
    | 'validationError'
    | 'scanExpired'
    | 'rateLimited'
    | 'terminalDisabled'
    | 'invalidDeviceToken'
    | 'notRegistered'
    | 'photoNotFound'
    | 'profileNotFound'

export interface Errors {
    errorType: ErrorTypes;
    kind: 'business' | 'system';
    message: string;
    statusCode?: number;
    code?: string;
    details?: Record<string, unknown>;
}