import {TerminalBlock} from "~/components/TerminalBlock";
import type {Errors} from "~/models/Errors";


interface UnknownErrorFrameFrameProps {
    error: Errors;
}
export const UnknownErrorFrame = ({error}: UnknownErrorFrameFrameProps) => {
    return (
        <TerminalBlock sectionTitle={"Терминал · неизвестная ошибка"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>{error.message}. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
