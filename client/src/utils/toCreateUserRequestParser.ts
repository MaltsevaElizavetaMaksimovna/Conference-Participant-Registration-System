import type {CreateUserRequest} from "~/models/CreateUserRequest";
import type {ExcelUserModel} from "~/models/parseModels/ExcelUserModel";


export const toCreateUserRequestParser = (data: ExcelUserModel[]): CreateUserRequest[] => {
    const result: CreateUserRequest[] = []
    for (const user of data) {
        result.push({
            firstName: user.firstName,
            lastName: user.lastName,
            surname: user.surname,
            post: user.post,
            organization: user.organization,
            status: "unregistered",
            marks: '',
            registrationPlace: null
        })
    }
    return result
}