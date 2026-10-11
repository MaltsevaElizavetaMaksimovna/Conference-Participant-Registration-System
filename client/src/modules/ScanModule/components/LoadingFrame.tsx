import {TerminalBlock} from "~/components/TerminalBlock";
import {Spinner} from "~/components/Spinner";

export const LoadingFrame = () => {
    return (
        <TerminalBlock sectionTitle={"Терминал · загрузка"}>
            <Spinner/>
            <h2>Загрузка...</h2>
        </TerminalBlock>
    );
};
