import {TerminalBlock} from "~/components/TerminalBlock";
import type {Errors} from "~/models/Errors";

interface NetworkErrorFrame {
    error: Errors;
}

export const NetworkErrorFrame = ({error}: NetworkErrorFrame) => {
    return (
        <TerminalBlock sectionTitle={"Терминал · ошибка сети"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>{error.message}. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
