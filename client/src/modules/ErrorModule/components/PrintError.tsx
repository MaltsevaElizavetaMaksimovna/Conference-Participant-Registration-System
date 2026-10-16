import {TerminalBlock} from "~/components/TerminalBlock";

export const PrintError = () => {
    return (
        <TerminalBlock sectionTitle={"Терминал · участник не найден"}>
            <div className="alert_icon">!</div>
            <h2 className='above_button_text'>Вы зарегистрированы, но наклейку напечатать не удалось. Обратитесь к стойке регистрации</h2>
        </TerminalBlock>
    );
};
