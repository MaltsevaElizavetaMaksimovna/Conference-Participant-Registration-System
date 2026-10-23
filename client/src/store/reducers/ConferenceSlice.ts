import {createAsyncThunk, createSlice} from "@reduxjs/toolkit";
import ConferenceService from "~/services/ConferenceService";
import {parseError} from "~/utils/ParseError";
import type {Errors} from "~/models/Errors";
import type {
    ActiveConferenceOut,
    ConferenceIn,
    ConferenceOut,
    PageConferenceOut,
} from "~/models/api";

type AsyncStatus = 'idle' | 'loading' | 'success' | 'error';


export interface ConferenceState {
    active: ActiveConferenceOut | null;
    activeStatus: AsyncStatus;
    activeError: Errors | null;

    list: ConferenceOut[];
    listTotal: number;
    listStatus: AsyncStatus;
    listError: Errors | null;

    selected: ConferenceOut | null;
    selectedStatus: AsyncStatus;
    selectedError: Errors | null;

    createStatus: AsyncStatus;
    createError: Errors | null;

    updateStatus: AsyncStatus;
    updateError: Errors | null;

    activateStatus: AsyncStatus;
    activateError: Errors | null;
}


const initialState: ConferenceState = {
    active: null,
    activeStatus: 'idle',
    activeError: null,

    list: [],
    listTotal: 0,
    listStatus: 'idle',
    listError: null,

    selected: null,
    selectedStatus: 'idle',
    selectedError: null,

    createStatus: 'idle',
    createError: null,

    updateStatus: 'idle',
    updateError: null,

    activateStatus: 'idle',
    activateError: null,
}

export const fetchActiveConference = createAsyncThunk<
    ActiveConferenceOut | null,
    void,
    { rejectValue: Errors }
>(
    'conference/fetchActiveConference',
    async (_, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.getActive()
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchConferences = createAsyncThunk<
    PageConferenceOut,
    { limit?: number, offset?: number },
    { rejectValue: Errors }
>(
    'conference/fetchConferences',
    async ({limit, offset}, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.list(limit, offset);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const fetchConferenceByID = createAsyncThunk<
    ConferenceOut,
    number,
    { rejectValue: Errors }
>(
    'conference/fetchConferenceByID',
    async (id, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.getById(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const createConference = createAsyncThunk<
    ConferenceOut,
    ConferenceIn,
    { rejectValue: Errors }
>(
    'conference/createConference',
    async (data, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.create(data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const updateConference = createAsyncThunk<
    ConferenceOut,
    { id: number, data: ConferenceIn },
    { rejectValue: Errors }
>(
    'conference/updateConference',
    async ({id, data}, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.update(id, data);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const activateConference = createAsyncThunk<
    ConferenceOut,
    number,
    { rejectValue: Errors }
>(
    'conference/activateConference',
    async (id, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.activate(id);
            return response.data
        } catch (e) {
            return rejectWithValue(parseError(e));
        }
    }
)

export const conferenceSlice = createSlice({
    name: 'conference',
    initialState,
    reducers: {
        clearActive(state) {
            state.active = null;
            state.activeStatus = 'idle';
            state.activeError = null;
        },
        clearSelected(state) {
            state.selected = null;
            state.selectedStatus = 'idle';
            state.selectedError = null;
        },
        clearErrors(state) {
            state.activeError = null;
            state.listError = null;
            state.selectedError = null;
            state.createError = null;
            state.updateError = null;
            state.activateError = null;
        },

    },
    extraReducers: builder => {
        builder.addCase(fetchActiveConference.pending, (state, action) => {
            state.activeStatus = 'loading'
            state.activeError = null
        })
        builder.addCase(fetchActiveConference.rejected, (state, action) => {
            state.activeStatus = 'error'
            state.activeError = action.payload ?? null;
        })
        builder.addCase(fetchActiveConference.fulfilled, (state, action) => {
            state.activeStatus = 'success'
            state.active = action.payload;
        })

        builder.addCase(fetchConferences.pending, (state, action) => {
            state.listStatus = 'loading'
            state.listError = null
        })
        builder.addCase(fetchConferences.rejected, (state, action) => {
            state.listStatus = 'error'
            state.listError = action.payload ?? null;
        })
        builder.addCase(fetchConferences.fulfilled, (state, action) => {
            state.listStatus = 'success'
            state.list = action.payload.items
            state.listTotal = action.payload.total
        })

        builder.addCase(fetchConferenceByID.pending, (state, action) => {
            state.selectedStatus = 'loading'
            state.selectedError = null
        })
        builder.addCase(fetchConferenceByID.rejected, (state, action) => {
            state.selectedStatus = 'error'
            state.selectedError = action.payload ?? null;
        })
        builder.addCase(fetchConferenceByID.fulfilled, (state, action) => {
            state.selectedStatus = 'success'
            state.selected = action.payload
        })

        builder.addCase(createConference.pending, (state, action) => {
            state.createStatus = 'loading'
            state.createError = null
        })
        builder.addCase(createConference.rejected, (state, action) => {
            state.createStatus = 'error'
            state.createError = action.payload ?? null;
        })
        builder.addCase(createConference.fulfilled, (state, action) => {
            state.createStatus = 'success'
            state.list.unshift(action.payload)
            state.listTotal += 1
        })

        builder.addCase(updateConference.pending, (state, action) => {
            state.updateStatus = 'loading'
            state.updateError = null
        })
        builder.addCase(updateConference.rejected, (state, action) => {
            state.updateStatus = 'error'
            state.updateError = action.payload ?? null;
        })
        builder.addCase(updateConference.fulfilled, (state, action) => {
            state.updateStatus = 'success'
            const updated = action.payload

            const idx = state.list.findIndex((c) => c.id === updated.id)
            if (idx !== -1) state.list[idx] = updated

            if(state.selected?.id === updated.id) {
                state.selected = updated
            }

            if (state.active?.id === updated.id) {
                state.active = {
                    id: updated.id,
                    date_to: updated.date_to,
                    title: updated.title,
                    badge_type: updated.badge_type,
                    date_from: updated.date_from,
                }
            }
        })

        builder.addCase(activateConference.pending, (state, action) => {
            state.activateStatus = 'loading'
            state.activateError = null
        })
        builder.addCase(activateConference.rejected, (state, action) => {
            state.activateStatus = 'error'
            state.activateError = action.payload ?? null;
        })
        builder.addCase(activateConference.fulfilled, (state, action) => {
            state.activateStatus = 'success'
            const activated = action.payload

            state.list.map((conf) => {
                return {
                    ...conf,
                    is_active: conf.id === activated.id,
                }
            })

            state.active = {
                id: activated.id,
                date_to: activated.date_to,
                title: activated.title,
                badge_type: activated.badge_type,
                date_from: activated.date_from,
            }
            state.activeStatus = 'success'
        })

    }
})

export const {clearActive, clearSelected, clearErrors} = conferenceSlice.actions
export const conferenceReducer = conferenceSlice.reducer