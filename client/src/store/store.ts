import {configureStore} from "@reduxjs/toolkit";
import {terminalReducer} from "~/store/reducers/TerminalSlice";
import {adminReducer} from "~/store/reducers/AdminSlice";
import {listenerMiddleware} from "~/store/listenerMiddleware";
import {conferenceReducer} from "~/store/reducers/ConferenceSlice";
import {authReducer} from "~/store/reducers/AuthSlice";
import {registerListeners} from "~/store/listeners";

registerListeners()

export const store = configureStore({
    reducer: {
        terminalReducer: terminalReducer,
        adminReducer: adminReducer,
        conferenceReducer: conferenceReducer,
        authReducer: authReducer,
    },
    middleware: (getDefaultMiddleware) =>
        getDefaultMiddleware().prepend(listenerMiddleware.middleware)
})


export type RootState = ReturnType<typeof store.getState>

export type AppDispatch = typeof store.dispatch