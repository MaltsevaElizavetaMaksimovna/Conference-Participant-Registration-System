import {useEffect, useState} from 'react';
import {useParams} from 'react-router';
import type {ProfileActive, ProfileRevoked} from '~/models/api';
import './public-profile.css';

type Profile = ProfileActive | ProfileRevoked;
type View = Profile | {status: 'loading' | 'missing' | 'error' | 'limited'};

export function PublicProfile() {
    const {token = ''} = useParams();
    return <main className="public-profile">
        <title>Профиль участника</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <meta name="robots" content="noindex,nofollow"/>
        <meta name="referrer" content="no-referrer"/>
        <section className="public-profile__card" aria-label="Профиль участника">
            {/^[A-Za-z0-9_-]{16,64}$/.test(token)
                ? <Badge key={token} token={token}/>
                : <h1>Профиль не найден</h1>}
        </section>
    </main>;
}

function Badge({token}: {token: string}) {
    const [view, setView] = useState<View>({status: 'loading'});
    const [attempt, setAttempt] = useState(0);
    const [photoFailed, setPhotoFailed] = useState(false);
    const endpoint = `/api/public/profile/${token}`;

    useEffect(() => {
        const controller = new AbortController();
        async function load() {
            try {
                const response = await fetch(endpoint, {
                    signal: controller.signal, credentials: 'omit', cache: 'no-store',
                    referrerPolicy: 'no-referrer', redirect: 'error',
                });
                let next: View;
                if (response.status === 404) next = {status: 'missing'};
                else if (response.status === 429) next = {status: 'limited'};
                else if (!response.ok) next = {status: 'error'};
                else {
                    const profile: Profile = await response.json();
                    next = profile?.status === 'active' || profile?.status === 'revoked'
                        ? profile : {status: 'error'};
                }
                if (!controller.signal.aborted) setView(next);
            } catch {
                if (!controller.signal.aborted) setView({status: 'error'});
            }
        }
        void load();
        return () => controller.abort();
    }, [endpoint, attempt]);

    switch (view.status) {
        case 'loading': return <p role="status">Загрузка профиля…</p>;
        case 'missing': return <h1>Профиль не найден</h1>;
        case 'revoked': return <h1>Бейдж аннулирован</h1>;
        case 'error':
        case 'limited': return <>
            <h1>{view.status === 'limited' ? 'Слишком много запросов' : 'Не удалось загрузить профиль'}</h1>
            {view.status === 'limited' && <p>Повторите попытку позже.</p>}
            <button className="btn btn_secondary" onClick={() => {
                setView({status: 'loading'});
                setAttempt(value => value + 1);
            }}>Попробовать снова</button>
        </>;
        case 'active': return <>
            <p className="public-profile__status">Действует</p>
            {view.photo_url === `${endpoint}/photo` && !photoFailed
                ? <img className="public-profile__photo" src={view.photo_url}
                       alt="Фото участника" referrerPolicy="no-referrer" onError={() => setPhotoFailed(true)}/>
                : <p className="public-profile__placeholder">Фото не загружено</p>}
            <h1>{view.full_name}</h1>
            <dl>
                <dt>Должность</dt><dd>{view.position || 'Не указана'}</dd>
                <dt>Организация</dt><dd>{view.organization || 'Не указана'}</dd>
            </dl>
        </>;
    }
}
