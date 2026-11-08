import {useAppDispatch, useAppSelector} from '~/hooks/redux';
import {confirmRegistration, reportError} from '~/store/reducers/TerminalSlice';

export const ConfirmFrame = () => {
    const dispatch = useAppDispatch();
    const {participant, scanId, idempotencyKey} = useAppSelector(state => state.terminalReducer);

    if (!participant || !scanId || !idempotencyKey) return null;

    function handleError() {
        if (participant && scanId) {
            dispatch(reportError({participant_id: participant.id, scan_id: scanId}))
        }
    }

    function handleApprove() {
        if (participant && scanId && idempotencyKey) {
            dispatch(confirmRegistration({
                data: {
                    participant_id: participant.id,
                    scan_id: scanId
                }, idempotencyKey
            }))
        }
    }

    return (
        <>
            <h1 className="terminal_title">Проверьте данные</h1>
            <p className="terminal_subtitle">Всё верно? Нажмите «Да, всё верно».</p>

            <div className="terminal_participant">
                <div className="terminal_participant_field">
                    <div className="terminal_participant_label">ФИО</div>
                    <div className="terminal_participant_value">{participant.full_name}</div>
                </div>
                <div className="terminal_participant_field">
                    <div className="terminal_participant_label">Должность</div>
                    <div className="terminal_participant_value">{participant.position}</div>
                </div>
                <div className="terminal_participant_field">
                    <div className="terminal_participant_label">Организация</div>
                    <div className="terminal_participant_value">{participant.organization}</div>
                </div>
            </div>

            <div className="terminal_actions">
                <button className="btn btn_secondary" onClick={handleError}>
                    Есть ошибка
                </button>
                <button className="btn btn_primary" onClick={handleApprove}>
                    Да, всё верно
                </button>
            </div>
        </>
    );
};