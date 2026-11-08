import { useState, useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import { uploadImportFile, fetchImportReport, resetImport } from '~/store/reducers/ImportSlice';

export const AdminImport = () => {
    const dispatch = useAppDispatch();

    const activeConference = useAppSelector(state => state.conferenceReducer.active);
    const { uploadStatus, uploadError, report, reportStatus } = useAppSelector(state => state.importReducer);

    const [isDownloading, setIsDownloading] = useState(false);

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files?.[0] || !activeConference) return;
        const file = e.target.files[0];

        dispatch(resetImport());

        try {
            const result = await dispatch(uploadImportFile({
                conferenceId: activeConference.id,
                file,
            })).unwrap();

            startPolling(activeConference.id, result.batch_id);
        } catch (err) {
            console.error('Ошибка загрузки файла:', err);
        }
    };

    const startPolling = (conferenceId: number, batchId: number) => {
        if ((window as any)._importInterval) {
            clearInterval((window as any)._importInterval);
        }

        (window as any)._importInterval = setInterval(async () => {
            const action = await dispatch(fetchImportReport({ conferenceId, batchId }));

            if (fetchImportReport.fulfilled.match(action)) {
                const status = action.payload.status;
                if (status !== 'running') {
                    clearInterval((window as any)._importInterval);
                    (window as any)._importInterval = null;
                }
            } else {
                clearInterval((window as any)._importInterval);
                (window as any)._importInterval = null;
            }
        }, 2000);
    };

    const handleDownloadTemplate = async () => {
        setIsDownloading(true);
        try {
            // 🟢 МОК: Генерируем пустой текстовый файл
            const content = "ID,Фамилия*,Имя*,Отчество,Должность,Организация\n";
            const blob = new Blob([content], { type: 'text/plain' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'import-template.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } finally {
            setIsDownloading(false);
        }
    };

    return (
        <div className="admin_main" style={{ padding: '32px' }}>
            <h1 style={{ marginBottom: '24px' }}>Импорт участников</h1>

            <div style={{ background: 'var(--tpu-white)', padding: '24px', borderRadius: '8px', border: '1px solid var(--tpu-border)', marginBottom: '24px' }}>
                <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Загрузить из файла</h2>
                <p style={{ color: 'var(--tpu-gray-text)', marginBottom: '16px', fontSize: '14px' }}>
                    Поддерживаются файлы .xlsx и .csv. Первая строка должна содержать заголовки.
                </p>

                <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                    <label
                        className={`btn btn_primary ${uploadStatus === 'loading' || !activeConference ? 'disabled' : ''}`}
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            cursor: (uploadStatus === 'loading' || !activeConference) ? 'not-allowed' : 'pointer',
                            opacity: (uploadStatus === 'loading' || !activeConference) ? 0.6 : 1
                        }}
                    >
                        {uploadStatus === 'loading' ? 'Загрузка...' : 'Выбрать файл'}
                        <input
                            type="file"
                            accept=".xlsx,.csv"
                            onChange={handleFileChange}
                            disabled={uploadStatus === 'loading' || !activeConference}
                            style={{ display: 'none' }}
                        />
                    </label>

                    <button
                        className="btn btn_secondary"
                        onClick={handleDownloadTemplate}
                        disabled={isDownloading}
                    >
                        {isDownloading ? 'Скачивание...' : 'Скачать шаблон'}
                    </button>
                </div>

                {!activeConference && <div style={{ color: 'var(--danger)', marginTop: '12px' }}>Нет активной конференции</div>}
                {uploadError && <div style={{ color: 'var(--danger)', marginTop: '12px' }}>{uploadError.message}</div>}
            </div>

            {/* Блок отчета */}
            {reportStatus !== 'idle' && (
                <div style={{ background: 'var(--tpu-white)', padding: '24px', borderRadius: '8px', border: '1px solid var(--tpu-border)' }}>
                    <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Отчёт об импорте</h2>

                    {reportStatus === 'loading' && !report && <p>Обработка файла... Пожалуйста, подождите.</p>}

                    {report && (
                        <>
                            <div style={{ display: 'flex', gap: '16px', marginBottom: '24px', flexWrap: 'wrap' }}>
                                <div className="badge badge_success">Загружено: {report.loaded}</div>
                                <div className="badge badge_warn">Обновлено: {report.updated}</div>
                                <div className="badge badge_muted">Без изменений: {report.unchanged}</div>
                                {report.skipped > 0 && <div className="badge" style={{ background: '#fee2e2', color: '#ef4444' }}>Пропущено: {report.skipped}</div>}
                            </div>

                            <p style={{ fontSize: '16px', fontWeight: 'bold', marginBottom: '16px' }}>{report.summary}</p>

                            {report.errors.length > 0 && (
                                <div style={{ marginBottom: '24px' }}>
                                    <h3 style={{ color: 'var(--danger)', marginBottom: '8px' }}>Ошибки:</h3>
                                    <ul style={{ listStyle: 'none', padding: 0 }}>
                                        {report.errors.map((err, i) => (
                                            <li key={i} style={{ fontSize: '14px', marginBottom: '4px' }}>
                                                {err.row ? `Строка ${err.row}: ` : ''} {err.message}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {report.conflicts.length > 0 && (
                                <div style={{ marginBottom: '24px' }}>
                                    <h3 style={{ color: 'var(--warn)', marginBottom: '8px' }}>Расхождения (не перезаписаны):</h3>
                                    <ul style={{ listStyle: 'none', padding: 0 }}>
                                        {report.conflicts.map((c, i) => (
                                            <li key={i} style={{ fontSize: '14px', marginBottom: '4px' }}>
                                                ID {c.external_id} (поле {c.field}): в системе «{c.system_value}», в файле «{c.file_value}»
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {report.warnings.length > 0 && (
                                <div>
                                    <h3 style={{ color: 'var(--warn)', marginBottom: '8px' }}>Предупреждения:</h3>
                                    <ul style={{ listStyle: 'none', padding: 0 }}>
                                        {report.warnings.map((w, i) => (
                                            <li key={i} style={{ fontSize: '14px', marginBottom: '4px' }}>{w}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
};