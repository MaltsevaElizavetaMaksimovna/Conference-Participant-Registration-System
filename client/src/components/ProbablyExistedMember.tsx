import type {UserData} from "~/models/response/UserData";

interface ProbablyExistedMemberProps {
    user: UserData
}

export const ProbablyExistedMember = ({user}: ProbablyExistedMemberProps) => {
    return (
        <div className="probably_existed_member_container">
            <span className='probably_existed_member_span'>{`${user.lastName} ${user.firstName} ${user.surname || ''}`}</span>
            <span className='probably_existed_member_span'>{user.organization || 'Не указана'}</span>
            <span className="badge badge_muted">Не зарегистрирован</span>
        </div>
    );
};
