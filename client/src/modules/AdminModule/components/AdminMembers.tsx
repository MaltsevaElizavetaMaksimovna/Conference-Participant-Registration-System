import {AdminLayout} from "~/modules/AdminModule/components/AdminLayout";
import React, {useMemo, useRef, useState} from "react";
import {useAppSelector} from "~/hooks/redux";
import {Spinner} from "~/components/Spinner";
import {AddUsersModal} from "~/modules/AdminModule/components/modals/AddUsersModal";
import {AdminPanelMember} from "~/components/AdminPanelMember";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import {ProbablyExistedModal} from "~/modules/AdminModule/components/modals/ProbablyExistedModal";
import writeExcelFile from 'write-excel-file/browser'
import {outputExampleModel} from "~/models/parseModels/Schemas/OutputExampleModel";

export const AdminMembers = () => {
    const [isLoading, setIsLoading] = useState(false);
    const [searchValue, setSearchValue] = useState("");
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [wasValidated, setWasValidated] = useState<boolean>(false);
    const [userForm, setUserForm] = useState<CreateUserRequest>({} as CreateUserRequest);


    const {userList} = useAppSelector(state => state.adminReducer)

    function handleSearch(e: React.ChangeEvent<HTMLInputElement>) {
        setSearchValue(e.target.value)
    }

    async function handleExampleLoad() {
        await writeExcelFile(outputExampleModel).toFile('example.xlsx');
    }

    const filteredUsers = useMemo(() => {
        const query = searchValue.trim().toLowerCase();
        if (!query) return userList

        const words = query.split(' ')
        return userList.filter(user => {
            const fullName = `${user.lastName} ${user.firstName} ${user.surname || ''}`.toLowerCase();
            return words.every((word) => fullName.includes(word));
        })
    }, [searchValue, userList])

    return (
        <>
            <AdminLayout>
                <main className="admin_main">
                    <div className="admin_header">
                        <h1>Участники</h1>
                        <div className="admin_header_buttons">
                            <button onClick={handleExampleLoad} className="btn btn_accent add_btn">
                                Скачать образец файла
                            </button>
                            <button onClick={() => setIsModalOpen(true)} className="btn btn_accent add_btn">
                                + Добавить вручную
                            </button>
                        </div>
                    </div>

                    <div className="search_row">
                        <input
                            onChange={(e) => handleSearch(e)}
                            className="input"
                            placeholder="Поиск по ФИО…"
                            value={searchValue}
                            autoComplete='off'
                        />

                    </div>
                    <div className="table_wrapper">
                        <table className="table">
                            <thead>
                            <tr>
                                <th>ФИО</th>
                                <th>Организация</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                            </thead>
                            <tbody>
                            {!isLoading
                                ? (filteredUsers.length != 0
                                    ? filteredUsers.map((user) => (
                                        <AdminPanelMember key={user.id} user={user}/>
                                    ))
                                    : <tr>
                                        <td><span className="">Участники не найдены</span></td>
                                    </tr>)
                                : (
                                    <tr>
                                        <td><Spinner/></td>
                                    </tr>
                                )
                            }
                            </tbody>
                        </table>
                    </div>
                </main>
            </AdminLayout>
            {
                isModalOpen
                    ? wasValidated
                        ? (
                            <ProbablyExistedModal
                                setIsModalOpen={setIsModalOpen}
                                setIsLoading={setIsLoading}
                                userForm={userForm}
                                setWasValidated={setWasValidated}
                                setUserForm={setUserForm}
                            />
                        )
                        : (
                            <AddUsersModal
                                setIsLoading={setIsLoading}
                                setIsModalOpen={setIsModalOpen}
                                userForm={userForm}
                                setUserForm={setUserForm}
                                setWasValidated={setWasValidated}
                            />
                        )
                    : null
            }
        </>
    )
        ;
};
