import {useAppSelector} from "~/hooks/redux";
import {AdminLayout} from "~/modules/AdminModule/components/AdminLayout";
import {AdminMembers} from "~/modules/AdminModule/components/AdminMembers";


export const AdminPanel = () => {
    const adminState = useAppSelector(state => state.adminReducer)
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
