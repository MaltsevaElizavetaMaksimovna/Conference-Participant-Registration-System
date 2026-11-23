import {adminApi} from '~/api/adminApi';
import type {
    OverflowItem, PageTemplateOut, PrintJobRefOut, ResizeIn, TemplateFieldOut,
    TemplateIn, TemplateOut, TemplateSaveOut, TemplateTestPrintIn,
} from '~/models/api';

const conferencePath = (id: number) => `/admin/conferences/${id}`;
const templatePath = (conferenceId: number, templateId: number) =>
    `${conferencePath(conferenceId)}/templates/${templateId}`;
const once = {'axios-retry': {retries: 0}};

export const TemplateService = {
    async list(conferenceId: number, signal: AbortSignal) {
        const path = `${conferencePath(conferenceId)}/templates`;
        const items: TemplateOut[] = [];
        const limit = 100;
        while (true) {
            const {data} = await adminApi.get<PageTemplateOut>(path, {signal, params: {limit, offset: items.length}});
            items.push(...data.items);
            if (!data.items.length || items.length >= data.total) return items;
        }
    },
    async fields(conferenceId: number, signal: AbortSignal) {
        const {data} = await adminApi.get<TemplateFieldOut[]>(`${conferencePath(conferenceId)}/template-fields`, {signal});
        return data;
    },
    async create(conferenceId: number, input: TemplateIn) {
        return (await adminApi.post<TemplateOut>(`${conferencePath(conferenceId)}/templates`, input, once)).data;
    },
    async save(template: TemplateOut, input: TemplateIn) {
        return (await adminApi.put<TemplateSaveOut>(templatePath(template.conference_id, template.id), input, once)).data;
    },
    async copy(template: TemplateOut, targetId: number) {
        const path = `${templatePath(template.conference_id, template.id)}/copy-to/${targetId}`;
        return (await adminApi.post<TemplateOut>(path, undefined, once)).data;
    },
    async resize(template: TemplateOut, input: ResizeIn) {
        return (await adminApi.post<TemplateOut>(`${templatePath(template.conference_id, template.id)}/resize`, input, once)).data;
    },
    async overflow(template: TemplateOut, signal: AbortSignal) {
        const path = `${templatePath(template.conference_id, template.id)}/overflow`;
        return (await adminApi.get<{items: OverflowItem[]}>(path, {signal})).data.items;
    },
    previewUrl(template: TemplateOut, participantId: number | null) {
        const params = new URLSearchParams({version: String(template.version)});
        if (participantId !== null) params.set('participant_id', String(participantId));
        return `/api${templatePath(template.conference_id, template.id)}/preview.png?${params}`;
    },
    async testPrint(template: TemplateOut, input: TemplateTestPrintIn) {
        const path = `${templatePath(template.conference_id, template.id)}/test-print`;
        return (await adminApi.post<PrintJobRefOut>(path, input, once)).data;
    },
};
