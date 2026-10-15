import {configureStore} from "@reduxjs/toolkit";
import {scanReducer} from "~/store/reducers/ScanSlice";
import {adminReducer} from "~/store/reducers/AdminSlice";
import {listenerMiddleware} from "~/store/listenerMiddleware";
import '~/store/listeners'


export const store = configureStore({
    reducer: {
        scanReducer: scanReducer,
        adminReducer: adminReducer,
    },
    middleware: (getDefaultMiddleware) =>
        getDefaultMiddleware().prepend(listenerMiddleware.middleware),
})


export type RootState = ReturnType<typeof store.getState>

export type AppDispatch = typeof store.dispatch