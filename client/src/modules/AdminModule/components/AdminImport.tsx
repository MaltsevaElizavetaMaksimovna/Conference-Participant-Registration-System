import { useState, useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '~/hooks/redux';
import {ImportService} from '~/services/ImportService';
import {parseError} from '~/utils/ParseError';
import { uploadImportFile, fetchImportReport } from '~/store/reducers/ImportSlice';

export const AdminImport = () => {
    const dispatch = useAppDispatch();

    const activeConference = useAppSelector(state => state.conferenceReducer.active);
    const {uploadStatus, uploadError, report, reportStatus, reportError, batch} =
        useAppSelector(state => state.importReducer);
    const [isDownloading, setIsDownloading] = useState(false);
    const [downloadError, setDownloadError] = useState('');

    useEffect(() => {
        if (!batch || batch.conferenceId !== activeConference?.id) return;
        let cancelled = false;
        let timer: number | undefined;
        const poll = async () => {
            const result = await dispatch(fetchImportReport(batch));
            if (!cancelled && fetchImportReport.fulfilled.match(result) &&
                (result.payload.status === 'running' || (result.payload.photos?.pending ?? 0) > 0)) {
                timer = window.setTimeout(poll, 2000);
            }
        };
        void poll();
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [batch, activeConference?.id, dispatch]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || !activeConference) return;
        e.target.value = '';
        void dispatch(uploadImportFile({conferenceId: activeConference.id, file}));
    };

    const handleDownloadTemplate = async () => {
        setIsDownloading(true);
        try {
            setDownloadError('');
            const {data: blob} = await ImportService.downloadTemplate();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'import-template.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            setDownloadError(parseError(error).message);
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
                {downloadError && <p role="alert">{downloadError}</p>}
                {uploadError && <div style={{ color: 'var(--danger)', marginTop: '12px' }}>{uploadError.message}</div>}
            </div>

            {/* Блок отчета */}
            {batch && batch.conferenceId === activeConference?.id && reportStatus !== 'idle' && (
                <div style={{ background: 'var(--tpu-white)', padding: '24px', borderRadius: '8px', border: '1px solid var(--tpu-border)' }}>
                    <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Отчёт об импорте</h2>

                    {reportError && <p role="alert">{reportError.message}</p>}
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
                                                {err.message}
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

                            {report.missing.length > 0 && (
                                <div>
                                    <h3>Отсутствуют в новом файле</h3>
                                    <ul>{report.missing.map(p => <li key={p.participant_id}>{p.full_name} ({p.external_id})</li>)}</ul>
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