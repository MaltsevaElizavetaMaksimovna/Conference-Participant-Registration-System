import {createAsyncThunk, createSlice, type PayloadAction} from "@reduxjs/toolkit";
import type {
    CheckDuplicatesIn,
    DuplicatesOut,
    PageParticipantShort, ParticipantCard,
    ParticipantCreatedOut, ParticipantCreateIn, ParticipantShort, ParticipantStats, ParticipantUpdateIn, PrinterOut,
    PrintJobOut,
    PrintJobRefOut,
    RegisterIn,
    RegisterOut
} from "~/models/api";
import type {AsyncStatus} from "~/store/reducers/ConferenceSlice";
import type {Errors} from "~/models/Errors";
import {type ParticipantListParams, ParticipantService} from "~/services/ParticipantService";
import {parseError} from "~/utils/ParseError";
import {DeskService} from "~/services/DeskService";

type ParticipantFilters = Required<ParticipantListParams>;

export interface AdminState {
    participants: ParticipantShort[];
    listTotal: number;
    listStatus: AsyncStatus;
    listError: Errors | null;

    filters: ParticipantFilters;

    selected: ParticipantCard | null;
    selectedStatus: AsyncStatus;
    selectedError: Errors | null;

    stats: ParticipantStats | null;

    printers: PrinterOut[];
    panelPrinterId: number | null;

    actionStatus: AsyncStatus;
    actionError: Errors | null;
    lastPrintJobId: number | null;
}

const initialFilters: ParticipantFilters = {
    q: '',
    filter: 'all',
    sort: 'name',
    limit: 50,
    offset: 0,
};

const initialState: AdminState = {
    participants: [],
    listTotal: 0,
    listStatus: 'idle',
    listError: null,

    filters: initialFilters,

    selected: null,
    selectedStatus: 'idle',
    selectedError: null,

    stats: null,

    printers: [],
    panelPrinterId: null,

    actionStatus: 'idle',
    actionError: null,
    lastPrintJobId: null,
};

export const fetchParticipants = createAsyncThunk<
    PageParticipantShort,
    ParticipantListParams | void,
    { rejectValue: Errors }
>(
    'admin/fetchParticipants',
    async (params, {rejectWithValue, getState}) => {
        try {
            const state = getState() as { adminReducer: AdminState };
            const current = state.adminReducer.filters
            const newParams = {...current, ...params}
            const response = await ParticipantService.list(newParams);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchParticipantsStats = createAsyncThunk<
    ParticipantStats,
    void,
    { rejectValue: Errors }
>(
    'admin/fetchParticipantsStats',
    async (_, {rejectWithValue}) => {
        try {
            const response = await ParticipantService.stats();
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchParticipantById = createAsyncThunk<
    ParticipantCard,
    number,
    { rejectValue: Errors }
>(
    'admin/fetchParticipantById',
    async (id, {rejectWithValue}) => {
        try {
            const response = await ParticipantService.getById(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const createParticipant = createAsyncThunk<
    ParticipantCreatedOut,
    ParticipantCreateIn,
    { rejectValue: Errors }
>(
    'admin/createParticipant',
    async (data, {rejectWithValue}) => {
        try {
            const response = await ParticipantService.create(data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const updateParticipant = createAsyncThunk<
    ParticipantCard,
    { id: number, data: ParticipantUpdateIn },
    { rejectValue: Errors }
>(
    'admin/updateParticipant',
    async ({id, data}, {rejectWithValue}) => {
        try {
            const response = await ParticipantService.update(id, data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const checkDuplicates = createAsyncThunk<
    DuplicatesOut,
    CheckDuplicatesIn,
    { rejectValue: Errors }
>(
    'admin/checkDuplicates',
    async (data, {rejectWithValue}) => {
        try {
            const response = await ParticipantService.checkDuplicates(data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const registerParticipantFromDesk = createAsyncThunk<
    RegisterOut,
    { id: number, data: RegisterIn },
    { rejectValue: Errors }
>(
    'admin/registerParticipantFromDesk',
    async ({id, data}, {rejectWithValue}) => {
        try {
            const response = await DeskService.register(id, data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const reprintSticker = createAsyncThunk<
    PrintJobRefOut,
    number,
    { rejectValue: Errors }
>(
    'admin/reprintSticker',
    async (id, {rejectWithValue}) => {
        try {
            const response = await DeskService.reprint(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const foreignCode = createAsyncThunk<
    PrintJobRefOut,
    number,
    { rejectValue: Errors }
>(
    'admin/foreignCode',
    async (id, {rejectWithValue}) => {
        try {
            const response = await DeskService.foreignCode(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const getPrintJob = createAsyncThunk<
    PrintJobOut,
    number,
    { rejectValue: Errors }
>(
    'admin/getPrintJob',
    async (id, {rejectWithValue}) => {
        try {
            const response = await DeskService.getPrintJob(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchPrinters = createAsyncThunk<
    PrinterOut[],
    void,
    { rejectValue: Errors }
>(
    'admin/fetchPrinters',
    async (_, {rejectWithValue}) => {
        try {
            const response = await DeskService.listPrinters();
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)


export const adminSlice = createSlice({
    name: 'admin',
    initialState,
    reducers: {
        setFilters(state, action: PayloadAction<Partial<ParticipantFilters>>) {
            state.filters = {...state.filters, ...action.payload};
        },
        resetFilters(state) {
            state.filters = initialFilters;
        },
        setSelected(state, action: PayloadAction<ParticipantCard | null>) {
            state.selected = action.payload;
        },
        clearSelected(state) {
            state.selected = null;
            state.selectedStatus = 'idle';
            state.selectedError = null;
        },
        clearActionError(state) {
            state.actionError = null;
        },
        updateParticipantFromSSE(state, action: PayloadAction<{
            id: number;
            status: ParticipantShort['status'];
            flags: ParticipantShort['flags']
        }>) {
            const {id, status, flags} = action.payload;
            const idx = state.participants.findIndex((p) => p.id === id);
            if (idx !== -1) {
                state.participants[idx].status = status;
                state.participants[idx].flags = flags;
            }
            if (state.selected?.id === id) {
                state.selected.status = status;
            }
        },
        updateStatsFromSSE(state, action: PayloadAction<ParticipantStats>) {
            state.stats = action.payload;
        },
    },
    extraReducers: (builder) => {

        builder.addCase(fetchParticipants.pending, (state) => {
            state.listStatus = 'loading'
            state.listError = null
        })
        builder.addCase(fetchParticipants.rejected, (state, action) => {
            state.listStatus = 'error'
            state.listError = action.payload ?? null;
        })
        builder.addCase(fetchParticipants.fulfilled, (state, action) => {
            state.listStatus = 'success'
            state.participants = action.payload.items;
            state.listTotal = action.payload.total;
        })

        builder.addCase(fetchParticipantsStats.fulfilled, (state, action) => {
            state.stats = action.payload;
        })

        builder.addCase(fetchParticipantById.pending, (state) => {
            state.selectedStatus = 'loading'
            state.selectedError = null
        })
        builder.addCase(fetchParticipantById.rejected, (state, action) => {
            state.selectedStatus = 'error'
            state.selectedError = action.payload ?? null;
        })
        builder.addCase(fetchParticipantById.fulfilled, (state, action) => {
            state.selectedStatus = 'success'
            state.selected = action.payload;
        })

        builder.addCase(createParticipant.pending, (state) => {
            state.actionStatus = 'loading'
            state.actionError = null
        })
        builder.addCase(createParticipant.rejected, (state, action) => {
            state.actionStatus = 'error'
            state.actionError = action.payload ?? null;
        })
        builder.addCase(createParticipant.fulfilled, (state, action) => {
            state.actionStatus = 'success'
            const participant = action.payload.participant;
            state.participants.unshift({
                id: participant.id,
                flags: participant.flags.map(f => f.code),
                status: participant.status,
                organization: participant.organization,
                full_name: `${participant.last_name} ${participant.first_name} ${participant.middle_name}`
            })
            state.listTotal += 1
        })

        builder.addCase(updateParticipant.pending, (state) => {
            state.actionStatus = 'loading'
            state.actionError = null
        })
        builder.addCase(updateParticipant.rejected, (state, action) => {
            state.actionStatus = 'error'
            state.actionError = action.payload ?? null;
        })
        builder.addCase(updateParticipant.fulfilled, (state, action) => {
            state.actionStatus = 'success'

            const updated = action.payload;
            const idx = state.participants.findIndex((p) => p.id === updated.id);
            if (idx !== -1) {
                state.participants[idx] = {
                    id: updated.id,
                    flags: updated.flags.map(f => f.code),
                    status: updated.status,
                    organization: updated.organization,
                    full_name: `${updated.last_name} ${updated.first_name} ${updated.middle_name}`
                }
            }

            if (state.selected?.id === updated.id) {
                state.selected = updated
            }
        })

        builder.addCase(registerParticipantFromDesk.pending, (state) => {
            state.actionStatus = 'loading'
            state.actionError = null
        })
        builder.addCase(registerParticipantFromDesk.rejected, (state, action) => {
            state.actionStatus = 'error'
            state.actionError = action.payload ?? null;
        })
        builder.addCase(registerParticipantFromDesk.fulfilled, (state, action) => {
            state.selectedStatus = 'success'
            const {participant, print_job_id} = action.payload;
            state.lastPrintJobId = print_job_id

            const idx = state.participants.findIndex((p) => p.id === participant.id);

            if (idx !== -1) {
                state.participants[idx].status = participant.status;
                state.participants[idx].flags = participant.flags.map(f => f.code);
            }

            if (state.selected?.id === participant.id) {
                state.selected = participant;
            }
        })

        builder.addCase(reprintSticker.fulfilled, (state, action) => {
            state.lastPrintJobId = action.payload.print_job_id;
        });

        builder.addCase(foreignCode.fulfilled, (state, action) => {
            state.lastPrintJobId = action.payload.print_job_id;
        });

        builder.addCase(fetchPrinters.fulfilled, (state, action) => {
            state.printers = action.payload;
        });

        builder.addCase(checkDuplicates.fulfilled, (state, action) => {

        });

    }
})

export const {
    clearActionError,
    updateParticipantFromSSE,
    resetFilters,
    setSelected,
    updateStatsFromSSE,
    setFilters,
    clearSelected
} = adminSlice.actions

export const adminReducer = adminSlice.reducer