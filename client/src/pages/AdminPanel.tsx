import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import {AdminMembers} from "~/modules/AdminModule/components/AdminMembers";
import {useEffect} from "react";
import {adminSlice} from "~/store/reducers/AdminSlice";


export const AdminPanel = () => {
    const adminState = useAppSelector(state => state.adminReducer)
    const dispatch = useAppDispatch()
    const {setPanelOpen, setPanelClose} = adminSlice.actions

    useEffect(() => {
        dispatch(setPanelOpen())
        return () => { dispatch(setPanelClose()) }
    }, [dispatch])

    switch (adminState.currentTab) {
        case 'members':
            return (
                <AdminMembers/>
            )
        case 'history':
            return (
                <AdminMembers/>
            )
        case 'templates':
            return (
                <AdminMembers/>
            )
        case 'terminals':
            return (
                <AdminMembers/>
            )
    }
};
