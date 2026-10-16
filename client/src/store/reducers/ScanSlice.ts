import {createAsyncThunk, createSlice, type PayloadAction} from "@reduxjs/toolkit";
import type {UserData} from "~/models/response/UserData";
import UserService from "~/services/UserService";
import type {Errors} from "~/models/response/Errors";
import {parseError} from "~/utils/ParseError";

export interface ScanState {
    status: 'scanning' | 'loading' | 'error' | 'confirm' | 'printing' | 'finished'
    user?: UserData
    error?: Errors
}

const initialState: ScanState = {
    status: 'scanning',
    user: {
        id: '12312',
        status: "unregistered",
        firstName: 'Иван ',
        lastName: 'Иванов',
        surname: 'Иванович',
        registrationDate: null,
        createdAt: new Date().toISOString(),
        registrationPlace: null
    }
}

export const findUser = createAsyncThunk(
    'scan/findUser',
    async (token: string, {rejectWithValue}) => {
        try {
            const response = await UserService.findUser(token)
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const completeRegistration = createAsyncThunk(
    'scan/completeRegistration',
    async (userId: string, {rejectWithValue}) => {
        try {
            const response = await UserService.completeRegistration(userId)
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const scanSlice = createSlice({
    name: 'scan',
    initialState,
    reducers: {
        resetStatus: (state) => {
            state.status = 'scanning';
            state.error = undefined
            state.user = undefined
        },
        flagMismatch: (state, action: PayloadAction<Errors>) => {
            state.status = 'error'
            state.error = action.payload
        },
        finishWithoutPrinting: (state) => {
            state.status = 'finished'
        },
        errorWhileFetchingConference: (state, action: PayloadAction<Errors>) => {
            state.status = 'error'
            state.error = action.payload
        }
    },
    extraReducers: (builder) => {
        builder.addCase(findUser.fulfilled, (state, action) => {
            if (action.payload.status == 'registered') {
                state.status = 'error'
                state.user = action.payload
                state.error = {
                    message: `Вы уже зарегистрированы (${action.payload.registrationDate}). Если вы не получили бейдж — обратитесь к стойке регистрации`,
                    errorType: 'alreadyRegistered'
                }
                return;
            }
            state.status = 'confirm'
            state.user = action.payload
        })
        builder.addCase(findUser.pending, (state) => {
            state.status = 'loading'
        })
        builder.addCase(findUser.rejected, (state, action) => {
            state.status = 'error'
            state.error = action.payload as Errors
        })

        builder.addCase(completeRegistration.fulfilled, (state, action) => {
            state.user = action.payload
            state.status = 'printing'
        })
        builder.addCase(completeRegistration.pending, (state) => {
            state.status = 'loading'
        })
        builder.addCase(completeRegistration.rejected, (state, action) => {
            state.status = 'error'
            state.error = action.payload as Errors
        })
    }
})

export const scanReducer = scanSlice.reducer;