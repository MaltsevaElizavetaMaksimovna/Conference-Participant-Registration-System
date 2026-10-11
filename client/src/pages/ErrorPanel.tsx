import {AlreadyRegisteredFrame} from "~/modules/ErrorModule/components/AlreadyRegisteredFrame";
import type {ScanState} from "~/store/reducers/ScanSlice";
import {
    NetworkErrorFrame,
    ServerErrorFrame,
    UncorrectedDataFrame,
    UnknownErrorFrame,
    UserNotFoundFrame
} from "~/modules/ErrorModule";


interface ErrorPanelProps {
    scanState: ScanState;
}

export const ErrorPanel = ({scanState}: ErrorPanelProps) => {

    switch (scanState.error!.errorType) {
        case 'alreadyRegistered':
            return (
                <AlreadyRegisteredFrame userData={scanState.user!}/>
            )
        case 'userNotFound':
            return (
                <UserNotFoundFrame/>
            )
        // case 'qrNotFound':
        //     return (
        //         <ConfirmFrame userData={scanState.user!}/>
        //     )
        case 'serverError':
            return (
                <ServerErrorFrame error={scanState.error!}/>
            )
        case 'networkError':
            return (
                <NetworkErrorFrame error={scanState.error!}/>
            )
        case 'uncorrectedData':
            return (
                <UncorrectedDataFrame/>
            )
        case 'unknownError':
            return (
                <UnknownErrorFrame error={scanState.error!}/>
            )
    }

};
