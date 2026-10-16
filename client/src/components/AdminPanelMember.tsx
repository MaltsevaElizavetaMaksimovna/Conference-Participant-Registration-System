import type {UserData} from "~/models/UserData";

interface AdminPanelMemberProps {
    user: UserData
}

export const AdminPanelMember = ({user}: AdminPanelMemberProps) => {
    return (
        <tr>
            <td>{`${user.lastName} ${user.firstName} ${user.surname || ''}`}</td>
            <td>{user.organization || 'Не указана'}</td>
            <td><span className="badge badge_muted">Не зарегистрирован</span></td>
            <td className="actions_cell">
                <button className="icon_btn">Печать</button>
                <button className="icon_btn">Правка</button>
            </td>
        </tr>
    );
};
