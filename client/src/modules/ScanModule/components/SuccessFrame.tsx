import {useAppSelector} from "~/hooks/redux";

export const SuccessFrame = () => {
    const { message } = useAppSelector(state => state.terminalReducer);
    return (
        <>
            <h1 className="terminal_title">Успешно!</h1>
            <p className="terminal_subtitle">{message}</p>
        </>
    );
};
