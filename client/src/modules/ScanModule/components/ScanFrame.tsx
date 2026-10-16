import {TerminalBlock} from "~/components/TerminalBlock";
import {useCallback} from "react";
import {type IDetectedBarcode, Scanner} from '@yudiel/react-qr-scanner';
import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import {findUser} from "~/store/reducers/ScanSlice";
import {Spinner} from "~/components/Spinner";

export const ScanFrame = () => {
    const {conference} = useAppSelector(state => state.conferenceReducer)
    const dispatch = useAppDispatch();
    const {status} = useAppSelector(state => state.scanReducer);

    const handleScanning = useCallback(async (result: IDetectedBarcode[]) => {
        if (!result.length || status === 'scanning' || !conference) return
        const userCode = result[0].rawValue
        try {
            await dispatch(findUser(userCode)).unwrap()
        } catch (e) {
            console.error(e);
        }
    }, [dispatch, status, conference]);

    return (
        <TerminalBlock sectionTitle={"Терминал · экран сканирования"}>
            {conference
                ? (
                    <>
                        <Scanner
                            onScan={handleScanning}
                            onError={(error) => console.error(error)}
                            styles={{container: {width: '340px', height: '340px', paddingBottom: '40px'}}}
                        />
                        <h2>Приложите QR-код к сканеру</h2>
                        <p>Код вы получили после онлайн-регистрации</p>
                    </>
                )
                : (
                    <>
                        <Spinner/>
                        <h2>Загрузка...</h2>
                    </>
                )

            }

        </TerminalBlock>
    );
};
