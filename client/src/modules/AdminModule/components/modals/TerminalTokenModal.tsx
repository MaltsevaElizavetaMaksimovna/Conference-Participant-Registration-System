interface Props {
    token: string;
    onClose: () => void;
}

export const TerminalTokenModal = ({ token, onClose }: Props) => {
    const handleCopy = () => {
        navigator.clipboard.writeText(token);
        alert('Токен скопирован в буфер обмена');
    };

    return (
        <div className="add_user_modal_container" onClick={onClose}>
            <div className="add_user_modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                <div className="add_user_modal_header">
                    <h2 className="add_user_modal_title">Токен терминала</h2>
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
                </div>
            </div>
        </div>
    );
};