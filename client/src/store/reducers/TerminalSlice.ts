import {createAsyncThunk, createSlice, type PayloadAction} from "@reduxjs/toolkit";
import type {Errors} from "~/models/Errors";
import {parseError} from "~/utils/ParseError";
import type {
    ConfirmIn,
    ConfirmOut,
    PingOut,
    ReportErrorIn,
    ReportErrorOut,
    ScanFound,
    TerminalPrintJobOut
} from "~/models/api";
import {type ScanResult, TerminalService} from "~/services/TerminalService";

export type TerminalScreen =
    | 'idle'
    | 'scanning'
    | 'confirm'
    | 'printing'
    | 'success'
    | 'error';

export interface TerminalState {
    connection: 'online' | 'offline' | 'disabled' | 'unknown';
    ping: PingOut | null;
    pingFailures: number;

    screen: TerminalScreen;
    message: string | null;

    scanId: string | null;
    participant: ScanFound['participant'] | null;
    idempotencyKey: string | null;

    printJobId: number | null;
    printStatus: TerminalPrintJobOut | null;

    error: Errors | null;
}

const initialState: TerminalState = {
    connection: 'unknown',
    ping: null,
    pingFailures: 0,

    screen: 'idle',
    message: null,

    scanId: null,
    participant: null,
    idempotencyKey: null,

    printJobId: null,
    printStatus: null,

    error: null,
};


export const pingTerminal = createAsyncThunk<
    PingOut,
    void,
    { rejectValue: Errors }
>(
    'terminal/pingTerminal',
    async (_, {rejectWithValue}) => {
        try {
            const response = await TerminalService.ping()
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const scanCode = createAsyncThunk<
    ScanResult,
    string,
    { rejectValue: Errors }
>(
    'terminal/scanCode',
    async (raw, {rejectWithValue}) => {
        try {
            const response = await TerminalService.scan(raw)
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const confirmRegistration = createAsyncThunk<
    ConfirmOut,
    { data: ConfirmIn, idempotencyKey: string },
    { rejectValue: Errors }
>(
    'terminal/confirmRegistration',
    async ({data, idempotencyKey}, {rejectWithValue}) => {
        try {
            const response = await TerminalService.confirm(data, idempotencyKey);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const reportError = createAsyncThunk<
    ReportErrorOut,
    ReportErrorIn,
    { rejectValue: Errors }
>(
    'terminal/reportError',
    async (data, {rejectWithValue}) => {
        try {
            const response = await TerminalService.reportError(data)
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchTerminalJob = createAsyncThunk<
    TerminalPrintJobOut,
    number,
    { rejectValue: Errors }
>(
    'terminal/fetchTerminalJob',
    async (id, {rejectWithValue}) => {
        try {
            const response = await TerminalService.getTerminalJob(id)
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const terminalSlice = createSlice({
    name: 'terminal',
    initialState,
    reducers: {
        terminalMounted() {

        },
        resetToIdle(state) {
            state.screen = 'idle';
            state.message = null;
            state.scanId = null;
            state.participant = null;
            state.idempotencyKey = null;
            state.printJobId = null;
            state.printStatus = null;
            state.error = null;
        },
        clearError(state) {
            state.error = null;
        },
        showConfirmScreen(state, action: PayloadAction<ScanFound>) {
            state.screen = 'confirm';
            state.scanId = action.payload.scan_id;
            state.participant = action.payload.participant;
            state.idempotencyKey = crypto.randomUUID();
            state.message = null;
            state.error = null;
        },
        showResult(state, action: PayloadAction<{ screen: 'success' | 'error'; message: string }>) {
            state.screen = action.payload.screen;
            state.message = action.payload.message;
        },
        setOffline(state) {
            state.connection = 'offline';
            state.screen = 'idle';
            state.message = 'Нет связи с сервером. Обратитесь к стойке регистрации';
        },
        setTerminalDisabled(state) {
            state.connection = 'disabled';
            state.message = 'Терминал не работает, воспользуйтесь соседним';
        },
    },
    extraReducers: (builder) => {

        builder.addCase(pingTerminal.rejected, (state, action) => {
            state.pingFailures += 1;
            const code = action.payload?.code;

            if (code === 'terminal_disabled' || code === 'invalid_device_token' || code === 'not_found') {
                state.connection = 'disabled';
                state.message = action.payload?.message ?? 'Терминал недоступен';
            } else if (state.pingFailures >= 2) {
                state.connection = 'offline';
            }
        })
        builder.addCase(pingTerminal.fulfilled, (state, action) => {
            state.connection = 'online'

            state.pingFailures = 0
            state.ping = action.payload
        })

        builder.addCase(scanCode.pending, (state) => {
            state.screen = 'scanning'
            state.error = null
        })
        builder.addCase(scanCode.rejected, (state, action) => {
            state.screen = 'error'
            state.error = action.payload ?? null
            state.message = action.payload?.message ?? 'Не удалось отсканировать код'
        })
        builder.addCase(scanCode.fulfilled, (state, action) => {
            const {result} = action.payload
            if (result === 'found') {
                state.screen = 'confirm'
                state.scanId = action.payload.scan_id
                state.participant = action.payload.participant
                state.idempotencyKey = crypto.randomUUID()
                state.message = null
            } else if (result === 'already_registered') {
                state.screen = 'error'
                state.message = action.payload.message
            } else if (result === 'not_found') {
                state.screen = 'error'
                state.message = action.payload.message
            }
        })

        builder.addCase(confirmRegistration.pending, (state) => {
            state.screen = 'printing'
            state.error = null
        })
        builder.addCase(confirmRegistration.rejected, (state, action) => {
            state.screen = 'error'
            state.error = action.payload ?? null
            state.message = action.payload?.message ?? 'Не удалось зарегистрировать'
        })
        builder.addCase(confirmRegistration.fulfilled, (state, action) => {
            const {result, message, print_job_id} = action.payload

            if (result === 'already_registered') {
                state.screen = 'error'
                state.message = message
                return
            }

            if (print_job_id) {
                state.screen = 'printing'
                state.printJobId = print_job_id
            } else {
                state.screen = 'success'
                state.message = message
            }
        })

        builder.addCase(reportError.rejected, (state, action) => {
            state.screen = 'error'
            state.error = action.payload ?? null
            state.message = action.payload?.message ?? 'Не удалось сообщить об ошибке'
        })
        builder.addCase(reportError.fulfilled, (state, action) => {
            state.screen = 'success'
            state.message = action.payload.message
        })

        builder.addCase(fetchTerminalJob.fulfilled, (state, action) => {
            const job = action.payload
            state.printStatus = job

            if (job.status === 'done') {
                state.screen = 'success'
                state.message = job.message
            } else if (job.status === 'error') {
                state.screen = 'error'
                state.message = job.message
            }
        })
    }
})

export const {
    resetToIdle,
    setOffline,
    setTerminalDisabled,
    showResult,
    showConfirmScreen,
    clearError,
    terminalMounted
} = terminalSlice.actions

export const terminalReducer = terminalSlice.reducer;