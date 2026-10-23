import {configureStore} from "@reduxjs/toolkit";
import {scanReducer} from "~/store/reducers/TerminalSlice";
import {adminReducer} from "~/store/reducers/AdminSlice";
import {listenerMiddleware} from "~/store/listenerMiddleware";
import '~/store/listeners'
import {conferenceReducer} from "~/store/reducers/ConferenceSlice";
import {authReducer} from "~/store/reducers/AuthSlice";


export const store = configureStore({
    reducer: {
        scanReducer: scanReducer,
        adminReducer: adminReducer,
        conferenceReducer: conferenceReducer,
        authReducer: authReducer,
    },
    middleware: (getDefaultMiddleware) =>
        getDefaultMiddleware().prepend(listenerMiddleware.middleware),
})


export type RootState = ReturnType<typeof store.getState>

export type AppDispatch = typeof store.dispatch