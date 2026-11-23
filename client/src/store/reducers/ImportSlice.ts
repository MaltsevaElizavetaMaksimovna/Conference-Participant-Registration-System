import {createAsyncThunk, createSlice} from '@reduxjs/toolkit';
import {ImportService} from '~/services/ImportService';
import {parseError} from '~/utils/ParseError';
import type {Errors} from '~/models/Errors';
import type {ImportAcceptedOut, ImportReportOut} from '~/models/api';

interface ImportState {
    uploadStatus: 'idle' | 'loading' | 'success' | 'error';
    uploadError: Errors | null;
    reportStatus: 'idle' | 'loading' | 'success' | 'error';
    report: ImportReportOut | null;
    reportError: Errors | null;
    batch: {conferenceId: number; batchId: number} | null;
}

const initialState: ImportState = {
    uploadStatus: 'idle',
    uploadError: null,
    reportStatus: 'idle',
    report: null,
    reportError: null,
    batch: null,
};


export const uploadImportFile = createAsyncThunk<
    ImportAcceptedOut,
    { conferenceId: number; file: File },
    { rejectValue: Errors }
>('import/upload',
    async ({conferenceId, file}, {rejectWithValue}) => {
        try {
            const response = await ImportService.uploadFile(conferenceId, file);
            return response.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);

export const fetchImportReport = createAsyncThunk<
    ImportReportOut,
    { conferenceId: number; batchId: number },
    { rejectValue: Errors }
>('import/fetchReport',
    async ({conferenceId, batchId}, {rejectWithValue}) => {
        try {
            const response = await ImportService.getReport(conferenceId, batchId);
            return response.data;
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);

export const importSlice = createSlice({
    name: 'import',
    initialState,
    reducers: {
        resetImport: () => initialState,
    },
    extraReducers: (builder) => {
        builder.addCase(uploadImportFile.pending, (state) => {
            state.uploadStatus = 'loading';
            state.uploadError = null;
            state.report = null;
            state.batch = null;
            state.reportError = null;
            state.reportStatus = 'idle';
        });
        builder.addCase(uploadImportFile.fulfilled, (state, action) => {
            state.uploadStatus = 'success';
            state.batch = {conferenceId: action.meta.arg.conferenceId, batchId: action.payload.batch_id};
        });
        builder.addCase(uploadImportFile.rejected, (state, action) => {
            state.uploadStatus = 'error';
            state.uploadError = action.payload ?? null;
        });

        builder.addCase(fetchImportReport.pending, (state) => {
            state.reportStatus = 'loading';
        });
        builder.addCase(fetchImportReport.fulfilled, (state, action) => {
            if (state.batch?.batchId !== action.meta.arg.batchId) return;
            state.reportStatus = 'success';
            state.report = action.payload;
        });
        builder.addCase(fetchImportReport.rejected, (state, action) => {
            if (state.batch?.batchId !== action.meta.arg.batchId || action.meta.aborted) return;
            state.reportError = action.payload ?? null;
            state.reportStatus = 'error';
        });
    },
});

export const {resetImport} = importSlice.actions;
export const importReducer = importSlice.reducer;