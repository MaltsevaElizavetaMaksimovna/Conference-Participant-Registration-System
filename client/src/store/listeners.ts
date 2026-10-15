import {startAppListening} from "~/store/listenerMiddleware";
import {completeRegistration, scanSlice} from "~/store/reducers/ScanSlice";
import {AUTO_RESET_TIMEOUT, FINISH_OR_ERROR_RESET_TIMEOUT, POLLING_INTERVAL} from "~/config/consts";
import {isAnyOf} from "@reduxjs/toolkit";
import {adminSlice, fetchUsers} from "~/store/reducers/AdminSlice";

const {resetStatus, flagMismatch} = scanSlice.actions;
const {setPanelOpen, setPanelClose} = adminSlice.actions;

startAppListening({
    predicate: (_, currentState, previousState) => {
        const isFalseTriggered = previousState.scanReducer.status === 'error' || previousState.scanReducer.status === 'finished'
        const isOnFinish = currentState.scanReducer.status === 'error' || currentState.scanReducer.status === 'finished'
        return !isFalseTriggered && isOnFinish
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