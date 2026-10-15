import {TerminalBlock} from "~/components/TerminalBlock";
import {scanSlice} from "~/store/reducers/ScanSlice";
import {useAppDispatch} from "~/hooks/redux";

export const UncorrectedDataFrame = () => {
    const {resetStatus} = scanSlice.actions
    const dispatch = useAppDispatch()

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
