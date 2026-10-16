import {createAsyncThunk, createSlice} from "@reduxjs/toolkit";
import ConferenceService from "~/services/ConferenceService";
import {parseError} from "~/utils/ParseError";
import type {Errors} from "~/models/response/Errors";

export type BadgeType = 'without' | 'one-sided' | 'two-sided'

export type ConferenceTemplates = ''

export interface Conference {
    id: string;
    name: string;
    badgeType: BadgeType;
    templates?: ConferenceTemplates;
    startDate: string;
    endDate: string;
}

export interface ConferenceState {
    conference: Conference | null;
    fetchingStatus: 'idle' | 'loading' | 'error';
    error?: Errors;
}


const initialState: ConferenceState = {
    conference: null,
    fetchingStatus: 'idle',
}

export const fetchConferenceSettings = createAsyncThunk(
    'conference/fetchConferenceSettings',
    async (_, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.getSettings()
            return response.data
        }
        catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const fetchTemplates = createAsyncThunk(
    'conference/fetchTemplates',
    async (conferenceId: string, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.getTemplates(conferenceId)
            return response.data
        }
        catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const updateSettings = createAsyncThunk(
    'conference/updateSettings',
    async (patch: Partial<Conference>, {rejectWithValue}) => {
        try {
            const response = await ConferenceService.updateSettings(patch)
            return response.data
        }
        catch (e) {
            return rejectWithValue(parseError(e))
        }
    }
)

export const conferenceSlice = createSlice({
    name: 'conference',
    initialState,
    reducers: {
        cleanConference: (state) => {
            state.conference = null
            state.fetchingStatus = 'idle'
        },
        terminalMounted: () => {}

    },
    extraReducers: builder => {
        builder.addCase(fetchConferenceSettings.fulfilled, (state, action) => {
            state.conference = action.payload
            state.fetchingStatus = 'idle'
        })
        builder.addCase(updateSettings.fulfilled, (state, action) => {
            state.conference = action.payload
        })
        builder.addCase(fetchTemplates.fulfilled, (state, action) => {
            if (state.conference){
                state.conference.templates = action.payload
            }

        })
        builder.addCase(fetchConferenceSettings.pending, (state) => {
            state.fetchingStatus = 'loading'
        })
        builder.addCase(fetchConferenceSettings.rejected, (state, action) => {
            state.fetchingStatus = 'error'
            state.error = action.payload as Errors
        })
        builder.addCase(fetchTemplates.rejected, (state, action) => {
            state.fetchingStatus = 'error'
            state.error = action.payload as Errors
        })
        builder.addCase(updateSettings.rejected, (state, action) => {
            state.fetchingStatus = 'error'
            state.error = action.payload as Errors
        })
    }
})


export const conferenceReducer = conferenceSlice.reducer