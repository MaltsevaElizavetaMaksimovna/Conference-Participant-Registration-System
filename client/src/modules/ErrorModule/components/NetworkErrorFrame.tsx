import {TerminalBlock} from "~/components/TerminalBlock";
import type {Errors} from "~/models/response/Errors";
import {END_RESET_TIMEOUT} from "~/config/consts";
import {useAutoReset} from "~/hooks/useAuroReset";

interface NetworkErrorFrame {
    error: Errors;
}

export const NetworkErrorFrame = ({error}: NetworkErrorFrame) => {
    useAutoReset(END_RESET_TIMEOUT);
    return (
        <TerminalBlock sectionTitle={"Терминал · ошибка сети"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>{error.message}. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
