import React, {useMemo} from "react";
import {addUser} from "~/store/reducers/AdminSlice";
import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import {ProbablyExistedMember} from "~/components/ProbablyExistedMember";
import {searchUsers} from "~/utils/searchUsers";

interface ProbablyExistedModalProps {
    setIsModalOpen: (isOpen: boolean) => void;
    setIsLoading: (isLoading: boolean) => void;
    userForm: CreateUserRequest;
    setWasValidated: (wasValidated: boolean) => void;
    setUserForm: (userForm: CreateUserRequest) => void;
}

export const ProbablyExistedModal = ({
                                         setIsModalOpen,
                                         setIsLoading,
                                         userForm,
                                         setWasValidated,
                                         setUserForm
                                     }: ProbablyExistedModalProps) => {
    const {userList} = useAppSelector(state => state.adminReducer);
    const dispatch = useAppDispatch()

    function handleCloseModal() {
        setIsModalOpen(false);
        setWasValidated(false);
    }

    async function handleSubmit() {
        try {
            await dispatch(addUser({
                ...userForm,
                status: 'registered',
                marks: 'Добавлен вручную',
                registrationPlace: 'Стойка регистрации'
            })).unwrap()
            setIsModalOpen(false);
            setUserForm({} as CreateUserRequest);
            setWasValidated(false);
        } catch (e) {
            console.error(e)
        }
    }

    const filteredUsers = useMemo(() => {
        const query = `${userForm.lastName} ${userForm.firstName} ${userForm.surname || ''}`.trim().toLowerCase();
        return searchUsers(userList, query)
    }, [userList, userForm.lastName, userForm.firstName, userForm.surname])

    return (
        <div
            onClick={handleCloseModal}
            className="add_user_modal_container"
        >
            <div
                onClick={(e) => e.stopPropagation()}
                className="add_user_modal probably_existed_member_modal"
            >
                <div className="add_user_modal_header">
                    <h2 className='add_user_modal_title'>Возможно, участник уже есть в списке</h2>
                    <div onClick={handleCloseModal} className="add_user_modal_close_btn">✖</div>
                </div>
                <div className="add_user_modal_main probably_existed_member_main">
                    <div className="probably_existed_member_main_container">
                        <table className='probably_existed_member_table'>
                            <thead>
                            <tr>
                                <th>ФИО</th>
                                <th>Организация</th>
                                <th>Статус</th>
                            </tr>
                            </thead>
                        </table>
                        <div className="probably_existed_modal_container">
                            {filteredUsers.length
                                ? filteredUsers.map((user) => (
                                    <ProbablyExistedMember key={user.id} user={user}/>
                                ))
                                : <span className="">Участники не найдены</span>
                            }
                        </div>
                    </div>
                    <button
                        onClick={() => handleSubmit()}
                        className="add_user_modal_add_btn"
                    >
                        Подтвердить добавление
                    </button>
                </div>
            </div>
        </div>
    );
};
