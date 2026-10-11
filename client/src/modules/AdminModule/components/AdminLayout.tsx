import type {ReactNode} from "react";
import {AdminPanelTab} from "~/components/AdminPanelTab";

interface AdminLayoutProps {
    children: ReactNode;
}

export const AdminLayout = ({children}: AdminLayoutProps) => {
    return (
        <div className="section">
            <div className="section_title">Админка регистратора</div>
            <div className="admin">
                <aside className="sidebar">
                    <div className="logo">🎫 Регистрация</div>
                    <AdminPanelTab thisTabName={'members'} tabText={'Участники'}/>
                    <AdminPanelTab thisTabName={'templates'} tabText={'Шаблоны печати'}/>
                    <AdminPanelTab thisTabName={'terminals'} tabText={'Терминалы'}/>
                    <AdminPanelTab thisTabName={'history'} tabText={'Журнал печати'}/>
                </aside>
                {children}
            </div>
        </div>
    );
};
