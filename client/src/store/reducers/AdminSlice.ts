import {createAsyncThunk, createSlice, type PayloadAction} from "@reduxjs/toolkit";
import type {AdminTabsModel} from "~/models/panels/AdminTabsModel";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import UserService from "~/services/UserService";
import type {UserData} from "~/models/response/UserData";

interface AdminState {
    currentTab: AdminTabsModel;
    userList: UserData[]
}

const initialState: AdminState = {
    currentTab: 'members',
    userList: [
        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },
        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },
        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },
        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },
        {
            status: 'unregistered',
            firstName: 'Ivan',
            lastName: 'Ivanov',
            surname: 'Ivanovich',
            organization: 'OOO Romashka',
            id: '12345',
            registrationDate: null,
            createdAt: new Date().toISOString(),
            registrationPlace: null
        },


    ],
}

export const addUser = createAsyncThunk(
    'admin/addUser',
    async (userForm: CreateUserRequest, {rejectWithValue}) => {
        try {
            const response =  await UserService.addUser(userForm)
            return response.data
        }
        catch (e) {
            return rejectWithValue(e)
        }
    }
)

export const fillUsersList = createAsyncThunk(
    'admin/fillUsersList',
    async (userData: CreateUserRequest[], {rejectWithValue}) => {
        try {
            const response = await UserService.fillUsersList(userData)
            return response.data
        }
        catch (e) {
            return rejectWithValue(e)
        }
    }
)


export const adminSlice = createSlice({
    name: 'admin',
    initialState,
    reducers: {
        setCurrentTab(state, action: PayloadAction<AdminTabsModel>) {
            state.currentTab = action.payload
        },
    },
    extraReducers: (builder) => {
        builder.addCase(addUser.fulfilled, (state, action: PayloadAction<UserData>) => {
            state.userList.push(action.payload)
        })
        builder.addCase(addUser.pending, (state, action) => {

        })
        builder.addCase(addUser.rejected, (state, action) => {

        })

        builder.addCase(fillUsersList.fulfilled, (state, action: PayloadAction<UserData[]>) => {
            state.userList = action.payload
        })
        builder.addCase(fillUsersList.pending, (state, action) => {

        })
        builder.addCase(fillUsersList.rejected, (state, action) => {

        })
    }
})

export const adminReducer = adminSlice.reducer