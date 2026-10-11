import {TerminalBlock} from "~/components/TerminalBlock";
import {Spinner} from "~/components/Spinner";

export const PrintingFrame = () => {
    return (
        <TerminalBlock sectionTitle={"Терминал · печать наклейки"}>
            <Spinner/>
            <h2>Печатается наклейка…</h2>
            <p>Подождите, это займёт пару секунд</p>
        </TerminalBlock>
    );
};
