export interface Errors {
    message: string
    errorType: 'userNotFound' | 'qrNotFound' | 'alreadyRegistered' | 'networkError' | 'uncorrectedData' | 'serverError' | 'unknownError' | 'printError'
    statusCode?: number
    isBusinessError?: boolean
}