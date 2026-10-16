import {createAsyncThunk, createSlice, type PayloadAction} from "@reduxjs/toolkit";
import type {AdminTabsModel} from "~/models/panels/AdminTabsModel";
import type {CreateUserRequest} from "~/models/CreateUserRequest";
import UserService from "~/services/UserService";
import type {UserData} from "~/models/UserData";
import type {RegisteredUsersStats} from "~/models/panels/RegisteredUsersStats";

interface AdminState {
    currentTab: AdminTabsModel;
    userList: UserData[],
    stats: RegisteredUsersStats | null,
    isPanelOpen: boolean,
    fetchStatus: 'idle' | 'loading' | 'success' | 'error',
}

const initialState: AdminState = {
    currentTab: 'members',
    isPanelOpen: false,
    stats: null,
    fetchStatus: 'idle',
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
        }, {
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

export const fetchUsers = createAsyncThunk(
    'admin/fetchUsers',
    async (_, {rejectWithValue}) => {
        try {
            const response = await UserService.getUsers()
            return response.data
        } catch (e) {
            return rejectWithValue(e)
        }
    },
    {
        condition: (_, {getState}) => {
            const state = getState() as {adminReducer: AdminState}
            return state.adminReducer.fetchStatus !== 'loading'
        }
    }
)

export const addUser = createAsyncThunk(
    'admin/addUser',
    async (userForm: CreateUserRequest, {rejectWithValue}) => {
        try {
            const response = await UserService.addUser(userForm)
            return response.data
        } catch (e) {
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
        } catch (e) {
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
        setPanelClose(state) {
            state.isPanelOpen = false
        },
        setPanelOpen(state) {
            state.isPanelOpen = true
        },
        updateUser(state, action: PayloadAction<UserData>) {
            const idx = state.userList.findIndex(user => user.id === action.payload.id)
            if (idx == -1) return
            state.userList[idx] = action.payload
        }
    },
    extraReducers: (builder) => {
        builder.addCase(addUser.fulfilled, (state, action) => {
            state.userList.push(action.payload)
        })
        builder.addCase(addUser.pending, (state, action) => {

        })
        builder.addCase(addUser.rejected, (state, action) => {

        })

        builder.addCase(fillUsersList.fulfilled, (state, action) => {
            state.userList = action.payload
        })
        builder.addCase(fillUsersList.pending, (state, action) => {

        })
        builder.addCase(fillUsersList.rejected, (state, action) => {

        })

        builder.addCase(fetchUsers.fulfilled, (state, action) => {
            state.fetchStatus = 'success'
            state.userList = action.payload
        })
        builder.addCase(fetchUsers.pending, (state, action) => {
            state.fetchStatus = 'loading'
        })
        builder.addCase(fetchUsers.rejected, (state, action) => {
            state.fetchStatus = 'error'
        })
    }
})

export const adminReducer = adminSlice.reducer