import {startAppListening} from "~/store/listenerMiddleware";
import {
    confirmRegistration,
    fetchTerminalJob,
    pingTerminal,
    resetToIdle,
    showResult, terminalMounted
} from "~/store/reducers/TerminalSlice";
import {AUTO_RESET_TIMEOUT, FINISH_OR_ERROR_RESET_TIMEOUT} from "~/config/consts";


export function registerListeners() {
    startAppListening({
        actionCreator: terminalMounted,
        effect: async (_, api) => {
            await api.dispatch(pingTerminal());

            while (true) {
                await api.delay(3000);
                const state = api.getState().terminalReducer;

                if (state.connection === 'disabled') {
                    break;
                }

                await api.dispatch(pingTerminal());
            }
        },
    });

    startAppListening({
        predicate: (_, currentState, previousState) => {
            return (
                previousState.terminalReducer.screen !== 'confirm' &&
                currentState.terminalReducer.screen === 'confirm'
            );
        },
        effect: async (_, api) => {
            api.cancelActiveListeners();

            const timeout = api.getState().terminalReducer.ping?.settings.idle_timeout_s
                ? api.getState().terminalReducer.ping!.settings.idle_timeout_s * 1000
                : AUTO_RESET_TIMEOUT;

            const acted = await api.condition(
                (_, state) => state.terminalReducer.screen !== 'confirm',
                timeout
            );

            if (!acted) {
                api.dispatch(resetToIdle());
            }
        },
    });

    startAppListening({
        predicate: (_, currentState, previousState) => {
            const wasFinal = previousState.terminalReducer.screen === 'success' || previousState.terminalReducer.screen === 'error';
            const isFinal = currentState.terminalReducer.screen === 'success' || currentState.terminalReducer.screen === 'error';
            return !wasFinal && isFinal;
        },
        effect: async (_, api) => {
            api.cancelActiveListeners();

            const timeout = api.getState().terminalReducer.ping?.settings.result_screen_s
                ? api.getState().terminalReducer.ping!.settings.result_screen_s * 1000
                : FINISH_OR_ERROR_RESET_TIMEOUT;

            const returned = await api.condition(resetToIdle.match, timeout);

            if (!returned) {
                api.dispatch(resetToIdle());
            }
        },
    });

    startAppListening({
        actionCreator: confirmRegistration.fulfilled,
        effect: async (action, api) => {
            if (!action.payload.print_job_id) return;

            const printJobId = action.payload.print_job_id;
            const timeout = 15_000;
            const startedAt = Date.now();

            while (Date.now() - startedAt < timeout) {
                await api.delay(500);

                const res = await api.dispatch(fetchTerminalJob(printJobId));

                if (fetchTerminalJob.fulfilled.match(res)) {
                    const status = res.payload.status;
                    if (status === 'done' || status === 'error') {
                        return;
                    }
                }
            }

            api.dispatch(showResult({
                screen: 'error',
                message: 'Не удалось получить статус печати. Обратитесь к стойке регистрации',
            }));
        },
    });
}

