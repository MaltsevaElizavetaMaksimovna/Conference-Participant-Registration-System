import {TerminalBlock} from "~/components/TerminalBlock";
import type {UserData} from "~/models/UserData";


interface AlreadyRegisteredFrameProps {
    userData: UserData;
}
export const AlreadyRegisteredFrame = ({userData}: AlreadyRegisteredFrameProps) => {
    return (
        <TerminalBlock sectionTitle={"Терминал · повторная регистрация"}>
            <div className="alert_icon">!</div>
            <h2>Вы уже зарегистрированы</h2>
            <p className='above_button_text'>Бейдж был выдан сегодня в {userData.registrationDate}</p>
        </TerminalBlock>
    );
};
