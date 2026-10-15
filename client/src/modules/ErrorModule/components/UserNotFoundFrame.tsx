import {TerminalBlock} from "~/components/TerminalBlock";


export const UserNotFoundFrame = () => {
    return (
        <TerminalBlock sectionTitle={"Терминал · участник не найден"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>Участник не найден. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
