import {TerminalBlock} from "~/components/TerminalBlock";
import type {Errors} from "~/models/Errors";

interface ServerErrorFrameProps {
    error: Errors;
}

export const ServerErrorFrame = ({error}: ServerErrorFrameProps) => {
    return (
        <TerminalBlock sectionTitle={"Терминал · ошибка сервера"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>{error.message}. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
