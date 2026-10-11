import {ConfirmFrame, LoadingFrame, PrintingFrame, ScanFrame} from "~/modules/ScanModule";
import {useAppSelector} from "~/hooks/redux";
import {AlreadyRegisteredFrame} from "~/modules/ErrorModule/components/AlreadyRegisteredFrame";
import {ErrorPanel} from "~/pages/ErrorPanel";


export const UserPanel = () => {
    const scanState = useAppSelector(state => state.scanReducer)

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
    }

};
