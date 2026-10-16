import {TerminalBlock} from "~/components/TerminalBlock";
import {scanSlice} from "~/store/reducers/ScanSlice";
import {useAppDispatch} from "~/hooks/redux";

export const PrintingSuccessFrame = () => {
    const {resetStatus} = scanSlice.actions
    const dispatch = useAppDispatch()

    function handleSubmit() {
        dispatch(resetStatus())
    }
    return (
        <TerminalBlock sectionTitle={"Терминал · печать наклейки"}>
            <h2>Регистрация завершена</h2>
            <p className='above_button_text'>Заберите наклейку и подойдите к стойке регистрации за бейджем</p>
            <button onClick={handleSubmit} className="btn btn_accent" >Готово</button>
        </TerminalBlock>
    );
};
