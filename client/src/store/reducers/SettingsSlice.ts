import {createAsyncThunk, createSlice} from '@reduxjs/toolkit';
import {parseError} from '~/utils/ParseError';
import type {
    TerminalOut,
    PrinterAdminOut,
    RoleOut,
    UserOut,
    PermissionOut,
    TerminalIn,
    TerminalTokenOut, PrinterIn, UserCreateIn, RoleIn
} from '~/models/api';
import {AdminService} from "~/services/AdminService";
import type {Errors} from "~/models/Errors";

interface SettingsState {
    terminals: TerminalOut[];
    printers: PrinterAdminOut[];
    users: UserOut[];
    roles: RoleOut[];
    permissions: PermissionOut[];

    status: 'idle' | 'loading' | 'success' | 'error';
    actionStatus: 'idle' | 'loading' | 'success' | 'error';
    error: Errors | null;

    lastIssuedToken: string | null;
}

const initialState: SettingsState = {
    terminals: [],
    printers: [],
    users: [],
    roles: [],
    permissions: [],
    status: 'idle',
    actionStatus: 'idle',
    error: null,
    lastIssuedToken: null,
};

export const fetchTerminals = createAsyncThunk(
    'settings/fetchTerminals',
    async (_, {rejectWithValue}) => {
        try {
            const res = await AdminService.listTerminals();
            return res.data.items;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const fetchPrinters = createAsyncThunk(
    'settings/fetchPrinters',

    async (_, {rejectWithValue}) => {
        try {
            const res = await AdminService.listPrinters();
            return res.data.items;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const fetchUsers = createAsyncThunk(
    'settings/fetchUsers',
    async (_, {rejectWithValue}) => {
        try {
            const res = await AdminService.listUsers();
            return res.data.items;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const fetchRoles = createAsyncThunk(
    'settings/fetchRoles',
    async (_, {rejectWithValue}) => {
        try {
            const res = await AdminService.listRoles();
            return res.data.items;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const fetchPermissions = createAsyncThunk(
    'settings/fetchPermissions',
    async (_, {rejectWithValue}) => {
        try {
            const res = await AdminService.listPermissions();
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const createTerminal = createAsyncThunk<
    TerminalOut,
    TerminalIn,
    { rejectValue: Errors }
>(
    'settings/createTerminal',
    async (data, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.createTerminal(data);
            dispatch(fetchTerminals());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);

export const issueTerminalToken = createAsyncThunk<
    TerminalTokenOut,
    number,
    { rejectValue: Errors }
>(
    'settings/issueTerminalToken',
    async (id, {rejectWithValue}) => {
        try {
            const res = await AdminService.issueTerminalToken(id);
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);
export const createPrinter = createAsyncThunk<
    PrinterAdminOut,
    PrinterIn,
    { rejectValue: Errors }
>(
    'settings/createPrinter',
    async (data, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.createPrinter(data);
            dispatch(fetchPrinters());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);

export const createUser = createAsyncThunk<
    UserOut,
    UserCreateIn,
    { rejectValue: Errors }
>(
    'settings/createUser',
    async (data, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.createUser(data);
            dispatch(fetchUsers()); // Обновляем список
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const blockUser = createAsyncThunk<
    UserOut,
    number,
    { rejectValue: Errors }
>(
    'settings/blockUser',
    async (id, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.blockUser(id);
            dispatch(fetchUsers());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const unblockUser = createAsyncThunk<
    UserOut,
    number,
    { rejectValue: Errors }
>(
    'settings/unblockUser',
    async (id, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.unblockUser(id);
            dispatch(fetchUsers());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const createRole = createAsyncThunk<
    RoleOut,
    RoleIn,
    { rejectValue: Errors }
>(
    'settings/createRole',
    async (data, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.createRole(data);
            dispatch(fetchRoles());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const updateRole = createAsyncThunk<
    RoleOut,
    { id: number; data: RoleIn },
    { rejectValue: Errors }
>(
    'settings/updateRole',
    async ({id, data}, {rejectWithValue, dispatch}) => {
        try {
            const res = await AdminService.updateRole(id, data);
            dispatch(fetchRoles());
            return res.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const deleteRole = createAsyncThunk<
    void,
    number,
    { rejectValue: Errors }
>(
    'settings/deleteRole',
    async (id, {rejectWithValue, dispatch}) => {
        try {
            await AdminService.deleteRole(id);
            dispatch(fetchRoles());
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    });

export const settingsSlice = createSlice({
    name: 'settings',
    initialState,
    reducers: {
        clearLastToken(state) {
            state.lastIssuedToken = null;
        },
        clearActionStatus(state) {
            state.actionStatus = 'idle';
            state.error = null;
        }
    },
    extraReducers: (builder) => {
        builder.addCase(fetchTerminals.fulfilled, (state, action) => {
            state.terminals = action.payload;
        });
        builder.addCase(fetchPrinters.fulfilled, (state, action) => {
            state.printers = action.payload;
        });
        builder.addCase(fetchUsers.fulfilled, (state, action) => {
            state.users = action.payload;
        });
        builder.addCase(fetchRoles.fulfilled, (state, action) => {
            state.roles = action.payload;
        });
        builder.addCase(fetchPermissions.fulfilled, (state, action) => {
            state.permissions = action.payload;
        });

        builder.addCase(createTerminal.pending, (state) => {
            state.actionStatus = 'loading';
            state.error = null;
        });
        builder.addCase(createTerminal.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(createTerminal.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });

        builder.addCase(createPrinter.pending, (state) => {
            state.actionStatus = 'loading';
            state.error = null;
        });
        builder.addCase(createPrinter.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(createPrinter.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });

        builder.addCase(issueTerminalToken.pending, (state) => {
            state.actionStatus = 'loading';
            state.error = null;
        });
        builder.addCase(issueTerminalToken.fulfilled, (state, action) => {
            state.actionStatus = 'success';
            state.lastIssuedToken = action.payload.token;
        });
        builder.addCase(issueTerminalToken.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });

        builder.addCase(createUser.pending, (state) => {
            state.actionStatus = 'loading';
            state.error = null;
        });
        builder.addCase(createUser.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(createUser.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });

        builder.addCase(blockUser.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(blockUser.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });
        builder.addCase(unblockUser.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(unblockUser.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });

        builder.addCase(createRole.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(updateRole.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(deleteRole.fulfilled, (state) => {
            state.actionStatus = 'success';
        });
        builder.addCase(createRole.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });
        builder.addCase(updateRole.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });
        builder.addCase(deleteRole.rejected, (state, action) => {
            state.actionStatus = 'error';
            state.error = action.payload ?? null;
        });
    },
});

export const {clearLastToken, clearActionStatus} = settingsSlice.actions;
export const settingsReducer = settingsSlice.reducer;