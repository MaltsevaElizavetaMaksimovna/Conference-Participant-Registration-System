import type {AdminTabsModel} from "~/models/panels/AdminTabsModel";
import {useAppDispatch, useAppSelector} from "~/hooks/redux";
import {adminSlice} from "~/store/reducers/AdminSlice";

interface AdminPanelTabProps {
    thisTabName: AdminTabsModel;
    tabText: string;
}

export const AdminPanelTab = ({thisTabName, tabText}: AdminPanelTabProps) => {
    const adminState = useAppSelector(state => state.adminReducer)
    const dispatch = useAppDispatch()
    const {setCurrentTab} = adminSlice.actions
    return (
        <div
            onClick={() => dispatch(setCurrentTab(thisTabName))}
            className={`nav_item ${adminState.currentTab == thisTabName && 'active'}`}
        >
            {tabText}
        </div>
    );
};
