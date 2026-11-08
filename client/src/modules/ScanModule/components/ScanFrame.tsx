import {useCallback} from "react";
import {type IDetectedBarcode, Scanner} from '@yudiel/react-qr-scanner';
import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import {scanCode} from "~/store/reducers/TerminalSlice";

export const ScanFrame = () => {
    const {active} = useAppSelector(state => state.conferenceReducer)
    const dispatch = useAppDispatch();
    const {screen} = useAppSelector(state => state.terminalReducer);

    const handleScanning = useCallback(async (result: IDetectedBarcode[]) => {
        if (!result.length || screen !== 'idle' || !active) return
        const userCode = result[0].rawValue
        try {
            await dispatch(scanCode(userCode)).unwrap()
        } catch (e) {
            console.error(e);
        }
    }, [dispatch, screen, active]);

    return (
        <>
            <h1 className="terminal_title">Приложите QR-код</h1>
            <p className="terminal_subtitle">Отсканируйте код из письма-приглашения</p>
            <div className="terminal_scan_frame">
                <Scanner
                    onScan={handleScanning}
                    onError={(e) => console.error(e)}
                    styles={{
                        container: { width: '100%', height: '100%' },
                        video: { objectFit: 'cover' }
                    }}
                />
            </div>
        </>
    );
};
