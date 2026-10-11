import React, {useState} from "react";
import {useAppDispatch} from "~/hooks/redux";
import {fillUsersList} from "~/store/reducers/AdminSlice";
import {readSheet} from "read-excel-file/browser";
import {schema} from "~/models/parseModels/Schemas/ExcelSchema";
import {AddUserModalInput} from "~/components/AddUserModalInput";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import {parser} from "~/utils/files/CSVParser";
import {getCached, makeCacheKey, setCache} from "~/utils/files/FileCacher";
import {toCreateUserRequestParser} from "~/utils/toCreateUserRequestParser";
import type {ExcelUserModel} from "~/models/parseModels/ExcelUserModel";

interface AddUsersModalProps {
    setIsModalOpen: (isOpen: boolean) => void;
    setIsLoading: (isLoading: boolean) => void;
    userForm: CreateUserRequest;
    setUserForm: (userForm: CreateUserRequest) => void;
    setWasValidated: (wasValidated: boolean) => void;
}


export const AddUsersModal = ({setIsModalOpen, setIsLoading, userForm, setUserForm, setWasValidated}: AddUsersModalProps) => {
    const dispatch = useAppDispatch();
    const [errors, setErrors] = useState<{firstName?: boolean, lastName?: boolean}>({});

    function handleCloseModal() {
        setIsModalOpen(false);
    }

    const validateUser = () => {
        const fields: typeof errors = {}
        if (!userForm.firstName?.trim()) fields.firstName = true;
        if (!userForm.lastName?.trim()) fields.lastName = true;
        setErrors(fields);
        return Object.keys(fields).length === 0;
    }

    async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
        if (!e.target.files || e.target.files.length == 0) return

        setIsLoading(true);
        const file = e.target.files[0]
        const cacheKey = makeCacheKey(file)

        try {
            const cached = getCached(cacheKey)
            if (cached) {
                dispatch(fillUsersList(cached))
                setIsModalOpen(false);
                return
            }

            if (e.target.files[0].name.toLowerCase().endsWith('.csv')) {
                const csv = await file.text()
                const userList: ExcelUserModel[] = []
                for await (const user of parser.parse(csv)) {
                    userList.push(user)
                }
                const fixedUserList = toCreateUserRequestParser(userList.slice(1)) // csv-parser не хочет пропускать строку с заголовками
                setCache(cacheKey, fixedUserList)
                dispatch(fillUsersList(fixedUserList))
                setIsModalOpen(false);
                return
            }

            const {objects, errors} = await readSheet(e.target.files[0], {schema})
            if (objects) {
                const fixedObjects = toCreateUserRequestParser(objects)
                setCache(cacheKey, fixedObjects)
                dispatch(fillUsersList(fixedObjects))
                setIsModalOpen(false);

            }
        } catch (e) {
            console.error(e)
        } finally {
            setIsLoading(false);
        }


    }

    const handleFormChange = (field: keyof CreateUserRequest) =>
        (e: React.ChangeEvent<HTMLInputElement>) => {
            setUserForm({...userForm, [field]: e.target.value})
        }

    async function handleSubmit() {
        if (!validateUser()) return
        setWasValidated(true);
    }

    return (
        <div
            onClick={handleCloseModal}
            className="add_user_modal_container"
        >
            <div
                onClick={(e) => e.stopPropagation()}
                className="add_user_modal"
            >
                <div className="add_user_modal_header">
                    <h2 className='add_user_modal_title'>Добавить участника</h2>
                    <div className="add_user_modal_header_block">
                        <h2 className='add_user_modal_title'>Добавить из файла:</h2>
                        <label className="file_input_label">
                            <input
                                onChange={handleChange}
                                className="input file_input" type={"file"}
                                accept={'.csv, .xlsx'}
                            />
                            <span className="file_input_btn">Выберите файл</span>
                            <span className="file_input_text">Файл не выбран</span>
                        </label>

                        <div onClick={handleCloseModal} className="add_user_modal_close_btn">✖</div>
                    </div>
                </div>
                <div className="add_user_modal_main">
                    <AddUserModalInput
                        value={userForm.firstName}
                        handleFormChange={handleFormChange("firstName")}
                        placeholder={'Введите имя*'}
                        error={errors.firstName}
                    />
                    <AddUserModalInput
                        value={userForm.lastName}
                        handleFormChange={handleFormChange('lastName')}
                        placeholder={'Введите фамилию*'}
                        error={errors.lastName}
                    />
                    <AddUserModalInput
                        value={userForm.surname}
                        handleFormChange={handleFormChange('surname')}
                        placeholder={'Введите отчество'}
                    />
                    <AddUserModalInput
                        value={userForm.post}
                        handleFormChange={handleFormChange('post')}
                        placeholder={'Введите должность(статус)'}
                    />
                    <AddUserModalInput
                        value={userForm.organization}
                        handleFormChange={handleFormChange('organization')}
                        placeholder={'Введите организацию'}
                    />
                    <button
                        onClick={handleSubmit}
                        className="add_user_modal_add_btn"
                    >
                        Добавить
                    </button>
                </div>
            </div>
        </div>
    );
};
