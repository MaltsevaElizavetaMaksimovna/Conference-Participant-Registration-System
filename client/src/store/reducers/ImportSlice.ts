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
}

const initialState: ImportState = {
    uploadStatus: 'idle',
    uploadError: null,
    reportStatus: 'idle',
    report: null,
};

let mockReportCallCount = 0;


export const uploadImportFile = createAsyncThunk<
    ImportAcceptedOut,
    { conferenceId: number; file: File },
    { rejectValue: Errors }
>('import/upload',
    // async ({conferenceId, file}, {rejectWithValue}) => {
    //     try {
    //         const response = await ImportService.uploadFile(conferenceId, file);
    //         return response.data;
    //     } catch (e) {
    //         return rejectWithValue(parseError(e));
    //     }
    // }
    async ({conferenceId, file}, {rejectWithValue}) => {
        try {
            // 🟢 МОК: Имитация загрузки
            console.log('🟢 [MOCK] Загрузка файла:', file.name);
            await new Promise(resolve => setTimeout(resolve, 1000)); // Задержка 1 сек
            mockReportCallCount = 0; // Сбрасываем счетчик

            return {batch_id: 999};
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
    // async ({conferenceId, batchId}, {rejectWithValue}) => {
    //     try {
    //         const response = await ImportService.getReport(conferenceId, batchId);
    //         return response.data;
    //     } catch (e) {
    //         return rejectWithValue(parseError(e));
    //     }
    // }
    async ({conferenceId, batchId}, {rejectWithValue}) => {
        try {
            // 🟢 МОК: Имитация получения отчета
            console.log(`🟢 [MOCK] Запрос отчета #${mockReportCallCount + 1}`);
            await new Promise(resolve => setTimeout(resolve, 500));
            mockReportCallCount += 1;

            if (mockReportCallCount === 1) {
                // Первый запрос — в процессе
                return {
                    batch_id: batchId, conference_id: conferenceId, source: 'file',
                    file_name: 'participants.xlsx', status: 'running',
                    summary: 'Обработка файла...', total_rows: 0, loaded: 0,
                    updated: 0, unchanged: 0, skipped: 0, errors: [], conflicts: [],
                    missing: [], warnings: [], started_at: new Date().toISOString(),
                    finished_at: null,
                };
            }

            // Второй запрос — готово (с ошибками и предупреждениями)
            return {
                batch_id: batchId, conference_id: conferenceId, source: 'file',
                file_name: 'participants.xlsx', status: 'done',
                summary: 'Загружено: 298, пропущено: 2', total_rows: 300,
                loaded: 295, updated: 3, unchanged: 0, skipped: 2,
                errors: [
                    {row: 15, reason: 'не указана фамилия', message: 'Строка 15: не указана фамилия'},
                    {row: 42, reason: 'дубликат', message: 'Строка 42: идентификатор уже существует'},
                ],
                conflicts: [
                    {
                        participant_id: 17,
                        external_id: 'P-1001',
                        field: 'organization',
                        system_value: 'ООО Ромашка',
                        file_value: 'ООО Ромашка (старое)'
                    }
                ],
                missing: [],
                warnings: ['Строка 21: фото не загружено'],
                started_at: new Date(Date.now() - 3000).toISOString(),
                finished_at: new Date().toISOString(),
            };
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
);

export const importSlice = createSlice({
    name: 'import',
    initialState,
    reducers: {
        resetImport(state) {
            state.uploadStatus = 'idle';
            state.uploadError = null;
            state.reportStatus = 'idle';
            state.report = null;
        },
    },
    extraReducers: (builder) => {
        builder.addCase(uploadImportFile.pending, (state) => {
            state.uploadStatus = 'loading';
            state.uploadError = null;
            state.report = null;
        });
        builder.addCase(uploadImportFile.fulfilled, (state) => {
            state.uploadStatus = 'success';
        });
        builder.addCase(uploadImportFile.rejected, (state, action) => {
            state.uploadStatus = 'error';
            state.uploadError = action.payload ?? null;
        });

        builder.addCase(fetchImportReport.pending, (state) => {
            state.reportStatus = 'loading';
        });
        builder.addCase(fetchImportReport.fulfilled, (state, action) => {
            state.reportStatus = 'success';
            state.report = action.payload;
        });
        builder.addCase(fetchImportReport.rejected, (state) => {
            state.reportStatus = 'error';
        });
    },
});

export const {resetImport} = importSlice.actions;
export const importReducer = importSlice.reducer;