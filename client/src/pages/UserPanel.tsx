import {ConfirmFrame, LoadingFrame, PrintingFrame, ScanFrame} from "~/modules/ScanModule";
import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import {ErrorPanel} from "~/pages/ErrorPanel";
import {PrintingSuccessFrame} from "~/modules/ScanModule/components/PrintingSuccessFrame";
import {WithoutPrintingSuccessFrame} from "~/modules/ScanModule/components/WithoutPrintingSuccessFrame";
import {useEffect} from "react";
import {conferenceSlice} from "~/store/reducers/ConferenceSlice";


export const UserPanel = () => {
    const dispatch = useAppDispatch();
    const {terminalMounted} = conferenceSlice.actions
    useEffect(() => {
        dispatch(terminalMounted())
    }, [dispatch])

    const scanState = useAppSelector(state => state.scanReducer)
    const badgeType = useAppSelector(state => state.conferenceReducer.conference?.badgeType)

    switch (scanState.status) {
        case 'scanning':
            return (
                <ScanFrame/>
            )
        case 'loading':
            return (
                <LoadingFrame/>
            )
        case 'confirm':
            return (
                <ConfirmFrame userData={scanState.user!}/>
            )
        case 'error':
            return (
                <ErrorPanel scanState={scanState}/>
            )
        case 'printing':
            return (
                <PrintingFrame/>
            )
        case 'finished':
            return badgeType === 'without'
                ? <WithoutPrintingSuccessFrame/>
                : <PrintingSuccessFrame/>
    }

};
