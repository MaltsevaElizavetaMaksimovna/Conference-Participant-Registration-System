import {useAppSelector} from "~/hooks/redux";

export const PrintingFrame = () => {
    const {message} = useAppSelector(state => state.terminalReducer);

    return (
        <>
            <div className="terminal_spinner"/>
            <h1 className="terminal_title">Печатается наклейка</h1>
            <p className="terminal_subtitle">
                {message || 'Заберите наклейку и подойдите к стойке регистрации'}
            </p>
        </>
    );
};
