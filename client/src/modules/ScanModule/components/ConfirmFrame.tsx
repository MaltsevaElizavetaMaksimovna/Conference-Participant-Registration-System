import {TerminalBlock} from "~/components/TerminalBlock";
import type {UserData} from "~/models/UserData";
import {useAppDispatch} from "~/hooks/redux";
import {completeRegistration, scanSlice} from "~/store/reducers/ScanSlice";

interface confirmFrameProps {
    userData: UserData;
}
export const ConfirmFrame = ({userData}: confirmFrameProps) => {
    const {flagMismatch} = scanSlice.actions
    const dispatch = useAppDispatch();

     function handleReject() {
        dispatch(flagMismatch({
                errorType: "uncorrectedData",
                message: 'Данные пользователя неверны',
                kind: "business"
            }
        ))
    }

    async function handleConfirm() {
        await dispatch(completeRegistration(userData.id))
    }

    return (
        <TerminalBlock sectionTitle={"Терминал · подтверждение данных"}>
            <div className="participant_card">
                <div className="label">ФИО</div>
                <div className="value">{`${userData.lastName} ${userData.firstName} ${userData.surname || ''}`}</div>

                <div className="label">Должность</div>
                <div className="value">{userData.post || 'Не указано'}</div>

                <div className="label">Организация</div>
                <div className="value">{ userData.organization || 'Не указано'}</div>

                <div className="card_actions">
                    <button onClick={handleReject} className="btn btn_secondary">✕ Не верно</button>
                    <button onClick={handleConfirm} className="btn btn_primary">✓ Всё верно</button>
                </div>
            </div>
        </TerminalBlock>
    );
};
