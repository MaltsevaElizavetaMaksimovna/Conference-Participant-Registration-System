import {configureStore} from "@reduxjs/toolkit";
import {scanReducer} from "~/store/reducers/ScanSlice";
import {adminReducer} from "~/store/reducers/AdminSlice";


export const Store = configureStore({
    reducer: {
        scanReducer: scanReducer,
        adminReducer: adminReducer,
    }
})


export type RootState = ReturnType<typeof Store.getState>

export type AppDispatch = typeof Store.dispatch