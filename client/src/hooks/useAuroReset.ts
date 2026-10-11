import {scanSlice} from "~/store/reducers/ScanSlice";
import {useAppDispatch} from "~/hooks/redux";
import {useEffect} from "react";


export function useAutoReset(timeoutMs: number) {
    const {resetStatus} = scanSlice.actions
    const dispatch = useAppDispatch()

    useEffect(() => {
        const timer = setTimeout(() => dispatch(resetStatus()), timeoutMs);
        return () => clearTimeout(timer);
    },[timeoutMs])
}