

export const schema = {
    id: {
        column: 'ID',
        type: String,
        required: true,
    },
    lastName: {
        column: 'Фамилия',
        type: String,
        required: true,
    },
    firstName: {
        column: 'Имя',
        type: String,
        required: true,
    },
    surname: {
        column: 'Отчество',
        type: String,
        required: false,
    },
    post: {
        column: 'Должность',
        type: String,
        required: false,
    },
    organization: {
        column: 'Организация',
        type: String,
        required: false,
    },
    lastNameEN: {
        column: 'Фамилия(English)',
        type: String,
        required: false,
    },
    firstNameEN: {
        column: 'Имя(English)',
        type: String,
        required: false,
    },
    surnameEN: {
        column: 'Отчество(English)',
        type: String,
        required: false,
    },
    postEN: {
        column: 'Должность(English)',
        type: String,
        required: false,
    },
    organizationEN: {
        column: 'Организация(English)',
        type: String,
        required: false,
    },

}