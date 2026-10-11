import {TerminalBlock} from "~/components/TerminalBlock";
import type {UserData} from "~/models/response/UserData";
import {useAutoReset} from "~/hooks/useAuroReset";
import {END_RESET_TIMEOUT} from "~/config/consts";


interface AlreadyRegisteredFrameProps {
    userData: UserData;
}
export const AlreadyRegisteredFrame = ({userData}: AlreadyRegisteredFrameProps) => {
    useAutoReset(END_RESET_TIMEOUT);
    return (
        <TerminalBlock sectionTitle={"Терминал · повторная регистрация"}>
            <div className="alert_icon">!</div>
            <h2>Вы уже зарегистрированы</h2>
            <p className='above_button_text'>Бейдж был выдан сегодня в {userData.registrationDate}</p>
        </TerminalBlock>
    );
};
