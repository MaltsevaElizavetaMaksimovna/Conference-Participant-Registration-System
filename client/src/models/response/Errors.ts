export interface Errors {
    message: string
    errorType: 'userNotFound' | 'qrNotFound' | 'alreadyRegistered' | 'networkError' | 'uncorrectedData' | 'serverError' | 'unknownError'
    statusCode?: number
}