import {TerminalBlock} from "~/components/TerminalBlock";
import {END_RESET_TIMEOUT} from "~/config/consts";
import {useAutoReset} from "~/hooks/useAuroReset";


export const UserNotFoundFrame = () => {
    useAutoReset(END_RESET_TIMEOUT)
    return (
        <TerminalBlock sectionTitle={"Терминал · участник не найден"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>Участник не найден. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
