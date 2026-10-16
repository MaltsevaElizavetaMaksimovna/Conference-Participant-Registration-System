import {TerminalBlock} from "~/components/TerminalBlock";
import {scanSlice} from "~/store/reducers/ScanSlice";
import {useAppDispatch} from "~/hooks/redux";

export const WithoutPrintingSuccessFrame = () => {
    const {resetStatus} = scanSlice.actions
    const dispatch = useAppDispatch()

    function handleSubmit() {
        dispatch(resetStatus())
    }
    return (
        <TerminalBlock sectionTitle={"Терминал · печать наклейки"}>
            <h2>Регистрация завершена</h2>
            <p className='above_button_text'>"Это окно закроется автоматически в течение 10 секунд"</p>
            <button onClick={handleSubmit} className="btn btn_accent" >Готово</button>
        </TerminalBlock>
    );
};
