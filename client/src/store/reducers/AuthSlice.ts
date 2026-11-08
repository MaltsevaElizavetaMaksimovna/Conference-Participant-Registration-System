import {createAsyncThunk, createSlice} from "@reduxjs/toolkit";
import type {Errors} from "~/models/Errors";
import {AuthService} from "~/services/AuthService";
import type {LoginIn, MeOut, PasswordChangeIn} from "~/models/api";
import {parseError} from "~/utils/ParseError";

interface AuthState {
    user: MeOut | null;
    status: 'idle' | 'loading' | 'authenticated' | 'unauthenticated';
    loginError: Errors | null;
}

const initialState: AuthState = {
    user: null,
    status: "idle",
    loginError: null,
}


export const login = createAsyncThunk<MeOut, LoginIn, { rejectValue: Errors }>(
    'auth/login',
    // async (data: LoginIn, {rejectWithValue}) => {
    //     try {
    //         const response = await AuthService.login(data);
    //         return response.data
    //     } catch (e) {
    //         return rejectWithValue(parseError(e))
    //     }
    // }
    async (data, { rejectWithValue }) => {
        // МОК
        await new Promise(r => setTimeout(r, 500));
        if (data.password !== 'admin') {
            return rejectWithValue({ message: 'Неверный пароль', errorType: 'invalidCredentials', kind: 'business' });
        }
        return {
            id: 1, full_name: 'Иванов И.И.', login: 'admin',
            role: { id: 1, name: 'Администратор' },
            permissions: ['participants.view', 'registration.desk'],
            panel_printer_id: null
        };
    }
)

export const fetchMe = createAsyncThunk<MeOut, void, { rejectValue: Errors }>(
    'auth/fetchMe',
    async (_, {rejectWithValue}) => {
        try {
            const response = await AuthService.fetchMe();
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const setPanelPrinter = createAsyncThunk<MeOut, number | null, { rejectValue: Errors }>(
    'auth/setPanelPrinter',
    async (printerId: number | null, {rejectWithValue}) => {
        try {
            const response = await AuthService.setPanelPrinter(printerId);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const changePassword = createAsyncThunk<void, PasswordChangeIn, { rejectValue: Errors }>(
    'auth/changePassword',
    async (data: PasswordChangeIn, {rejectWithValue}) => {
        try {
            return await AuthService.changePassword(data);
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const logout = createAsyncThunk<void, void, { rejectValue: Errors }>(
    'auth/logout',
    async (_, {rejectWithValue}) => {
        try {
            return await AuthService.logout();
        } catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)


export const authSlice = createSlice({
    name: 'auth',
    initialState,
    reducers: {
        logoutLocal(state) {
            state.status = 'unauthenticated';
            state.user = null;
            state.loginError = null;
        },
        clearLoginError(state) {
            state.loginError = null;
        }

    },
    extraReducers: builder => {
        builder.addCase(login.pending, (state) => {
            state.status = 'loading'
            state.loginError = null;
        })
        builder.addCase(login.rejected, (state, action) => {
            if (state.status !== 'authenticated') {
                state.status = 'unauthenticated';
            }
            state.loginError = action.payload ?? null;
        })
        builder.addCase(login.fulfilled, (state, action) => {
            state.status = 'authenticated'
            state.user = action.payload;
            state.loginError = null;
        })

        builder.addCase(logout.rejected, (state) => {
            state.status = 'unauthenticated'
            state.loginError = null;
            state.user = null
        })
        builder.addCase(logout.fulfilled, (state) => {
            state.status = 'unauthenticated'
            state.user = null;
            state.loginError = null;
        })

        builder.addCase(fetchMe.pending, (state) => {
            if (state.status === 'authenticated') return
            state.status = 'loading'
        })
        builder.addCase(fetchMe.rejected, (state) => {
            state.status = 'unauthenticated'
            state.user = null
        })
        builder.addCase(fetchMe.fulfilled, (state, action) => {
            state.status = 'authenticated'
            state.user = action.payload;
            state.loginError = null;
        })

        builder.addCase(setPanelPrinter.fulfilled, (state, action) => {
            state.user = action.payload;
        })

    }
})

export const {logoutLocal, clearLoginError} = authSlice.actions

export const authReducer = authSlice.reducer