import {useAppSelector} from "~/hooks/redux";

export const ErrorFrame = () => {
    const { message } = useAppSelector(state => state.terminalReducer);
    return (
        <>
            <div className="terminal_error_icon">!</div>
            <h1 className="terminal_title">Внимание</h1>
            <p className="terminal_subtitle">{message}</p>
        </>
    );
};
