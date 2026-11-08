import {createStringCSVParser} from "web-csv-toolbox";

export const parser = createStringCSVParser({
    delimiter: ";",
    header: [
        'id',
        'lastName',
        'firstName',
        'surname',
        'post',
        'organization',
        'lastNameEN',
        'firstNameEN',
        'surnameEN',
        'postEN',
        'organizationEN'
    ]
})

