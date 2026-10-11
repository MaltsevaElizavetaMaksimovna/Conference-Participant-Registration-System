import {TerminalBlock} from "~/components/TerminalBlock";
import {useCallback, useRef} from "react";
import {type IDetectedBarcode, Scanner} from '@yudiel/react-qr-scanner';
import {useAppDispatch} from "~/hooks/redux";
import {findUser} from "~/store/reducers/ScanSlice";

export const ScanFrame = () => {
    const hasScannedRef = useRef<boolean>(false);
    const dispatch = useAppDispatch();

    const handleScanning = useCallback(async (result: IDetectedBarcode[]) => {
        if (!result.length || hasScannedRef.current) return
        hasScannedRef.current = true;
        const userCode = result[0].rawValue
        try {
            await dispatch(findUser(userCode)).unwrap()
        } catch (e) {
            console.error(e);
        }
    }, [dispatch]);

    return (
            <TerminalBlock sectionTitle={"Терминал · экран сканирования"}>
                <Scanner
                    onScan={handleScanning}
                    onError={(error) => console.error(error)}
                    styles={{container: {width: '340px', height: '340px', paddingBottom: '40px'}}}
                />
                <h2>Приложите QR-код к сканеру</h2>
                <p>Код вы получили после онлайн-регистрации</p>
            </TerminalBlock>
    );
};
