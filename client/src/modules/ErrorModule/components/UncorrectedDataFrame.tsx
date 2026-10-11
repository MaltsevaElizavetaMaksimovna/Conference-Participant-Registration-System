import {TerminalBlock} from "~/components/TerminalBlock";
import {scanSlice} from "~/store/reducers/ScanSlice";
import {useAppDispatch} from "~/hooks/redux";
import {useEffect} from "react";
import {END_RESET_TIMEOUT} from "~/config/consts";
import {useAutoReset} from "~/hooks/useAuroReset";

export const UncorrectedDataFrame = () => {
    const {resetStatus} = scanSlice.actions
    const dispatch = useAppDispatch()
    useAutoReset(END_RESET_TIMEOUT)

    function handleSubmit() {
        dispatch(resetStatus())
    }
    return (
        <TerminalBlock sectionTitle={"Терминал · неверные данные"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>Подойдите к стойке регистрации — сотрудник исправит данные</h2>
            <button onClick={() => handleSubmit()} className="btn btn_accent" >Готово</button>
        </TerminalBlock>
    );
};
