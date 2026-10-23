import {startAppListening} from "~/store/listenerMiddleware";
import {completeRegistration, terminalSlice} from "~/store/reducers/TerminalSlice";
import {AUTO_RESET_TIMEOUT, FINISH_OR_ERROR_RESET_TIMEOUT, POLLING_INTERVAL} from "~/config/consts";
import {isAnyOf} from "@reduxjs/toolkit";
import {adminSlice, fetchUsers} from "~/store/reducers/AdminSlice";
import {
    conferenceSlice,
    fetchConferenceSettings,
} from "~/store/reducers/ConferenceSlice";

const {resetStatus, flagMismatch, finishWithoutPrinting, errorWhileFetchingConference} = terminalSlice.actions;
const {setPanelOpen, setPanelClose} = adminSlice.actions;
const {terminalMounted} = conferenceSlice.actions;

startAppListening({
    predicate: (_, currentState, previousState) => {
        const isFalseTriggered = previousState.scanReducer.status === 'error' || previousState.scanReducer.status === 'finished'
        const isOnFinish = currentState.scanReducer.status === 'error' || currentState.scanReducer.status === 'finished'
        if (isFalseTriggered || !isOnFinish) return false

        return currentState.scanReducer.error?.kind == 'business';
    },
    effect: async (_, api) => {
        api.cancelActiveListeners()
        const isReturnedByButton = await api.condition(resetStatus.match, FINISH_OR_ERROR_RESET_TIMEOUT)
        if (!isReturnedByButton) api.dispatch(resetStatus())
    }

})

startAppListening({
    predicate: (_, currentState, previousState) => {
        if (currentState.scanReducer.status === previousState.scanReducer.status) return false
        return currentState.scanReducer.status === 'confirm';
    },
    effect: async (_, api) => {
        api.cancelActiveListeners()
        const isButtonPressed = await api.condition(isAnyOf(completeRegistration.pending, flagMismatch.match), AUTO_RESET_TIMEOUT)
        if (!isButtonPressed) api.dispatch(resetStatus())
    }
})

startAppListening({
    actionCreator: setPanelOpen,
    effect: async (_, api) => {
        api.cancelActiveListeners()
        await api.dispatch(fetchUsers())

        while (api.getState().adminReducer.isPanelOpen) {
            await api.delay(POLLING_INTERVAL)
            if (document.visibilityState === 'hidden') continue
            await api.dispatch(fetchUsers())
        }
    }
})

startAppListening({
    actionCreator: setPanelClose,
    effect: async (_, api) => {
        api.cancelActiveListeners()
    }
})

startAppListening({
    actionCreator: completeRegistration.fulfilled,
    effect: async (_, api) => {
        const state = api.getState()

        if (state.conferenceReducer.conference?.badgeType == 'without') {
            api.dispatch(finishWithoutPrinting())
        }
    }
})

startAppListening({
    actionCreator: terminalMounted,
    effect: async (_, api) => {
        api.cancelActiveListeners()

        if (api.getState().conferenceReducer.conference !== null) return;

        const result = await api.dispatch(fetchConferenceSettings())

        if (fetchConferenceSettings.rejected.match(result)) {
            api.dispatch(errorWhileFetchingConference(api.getState().conferenceReducer.error!))
        }

    }
})

startAppListening({
    actionCreator: errorWhileFetchingConference,
    effect: async (_, api) => {
        api.cancelActiveListeners();

        while (true) {
            await api.delay(15_000);

            const result = await api.dispatch(fetchConferenceSettings());
            if (fetchConferenceSettings.fulfilled.match(result)) {
                return;
            }
        }
    },
});

startAppListening({
    actionCreator: fetchConferenceSettings.fulfilled,
    effect: (_, api) => {
        const status = api.getState().scanReducer.status;

        if (status === 'error') {
            api.dispatch(resetStatus());
        }
    },
});