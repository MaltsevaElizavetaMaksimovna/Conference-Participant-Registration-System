import {useState} from 'react';

interface Props {
    token: string;
    onClose: () => void;
    title?: string;
}

export const TerminalTokenModal = ({token, onClose, title = 'Токен терминала'}: Props) => {
    const [copyStatus, setCopyStatus] = useState('');
    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(token);
            setCopyStatus('Токен скопирован');
        } catch {
            setCopyStatus('Не удалось скопировать. Выделите токен и скопируйте вручную.');
        }
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">{title}</h2>
                    <button className="icon_btn" onClick={onClose}>✖</button>
                </div>

                <div style={{ padding: '24px' }}>
                    <p style={{ color: 'var(--danger)', marginBottom: '16px', fontWeight: 'bold' }}>
                        ⚠️ Сохраните этот токен! Он показывается только один раз.
                    </p>
                    <div style={{
                        background: 'var(--tpu-gray-bg)',
                        padding: '16px',
                        borderRadius: '6px',
                        fontFamily: 'monospace',
                        wordBreak: 'break-all',
                        marginBottom: '16px'
                    }}>
                        {token}
                    </div>
                    <button className="btn btn_primary" onClick={handleCopy}>Скопировать</button>
                    {copyStatus && <p role="status">{copyStatus}</p>}
                </div>
            </div>
        </div>
    );
};
