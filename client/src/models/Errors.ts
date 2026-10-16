
export type ErrorKind = 'system' | 'business'

export type ErrorTypes = 'userNotFound' | 'alreadyRegistered' | 'networkError' | 'uncorrectedData' | 'serverError' | 'unknownError' | 'printError'

export interface Errors {
    message: string
    errorType: ErrorTypes
    statusCode?: number
    kind: ErrorKind
}