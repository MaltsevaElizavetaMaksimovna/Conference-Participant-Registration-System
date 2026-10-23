// ~/models/api/index.ts
import type { components } from '~/services/types/api';

export type MeOut = components['schemas']['MeOut'];
export type LoginIn = components['schemas']['LoginIn'];
export type PasswordChangeIn = components['schemas']['PasswordChangeIn'];
export type PanelPrinterIn = components['schemas']['PanelPrinterIn'];

export type ParticipantCard = components['schemas']['ParticipantCard'];
export type ParticipantShort = components['schemas']['ParticipantShort'];
export type ParticipantCreateIn = components['schemas']['ParticipantCreateIn'];
export type ParticipantUpdateIn = components['schemas']['ParticipantUpdateIn'];
export type ParticipantStats = components['schemas']['ParticipantStats'];
export type ParticipantCreatedOut = components['schemas']['ParticipantCreatedOut'];

export type DuplicatesOut = components['schemas']['DuplicatesOut'];
export type CheckDuplicatesIn = components['schemas']['CheckDuplicatesIn'];

export type RegisterOut = components['schemas']['RegisterOut'];
export type RegisterIn = components['schemas']['RegisterIn'];

export type ConferenceOut = components['schemas']['ConferenceOut'];
export type ActiveConferenceOut = components['schemas']['ActiveConferenceOut'];
export type ConferenceIn = components['schemas']['ConferenceIn'];

export type TemplateOut = components['schemas']['TemplateOut'];
export type TemplateFieldOut = components['schemas']['TemplateFieldOut'];
export type TemplateIn = components['schemas']['TemplateIn'];

export type ScanFound = components['schemas']['ScanFound'];
export type ScanNotFound = components['schemas']['ScanNotFound'];
export type ScanAlreadyRegistered = components['schemas']['ScanAlreadyRegistered'];
export type ScanParticipant = components['schemas']['ScanParticipant'];
export type ScanIn = components['schemas']['ScanIn'];

export type ConfirmIn = components['schemas']['ConfirmIn'];
export type ConfirmOut = components['schemas']['ConfirmOut'];

export type ReportErrorIn = components['schemas']['ReportErrorIn'];
export type ReportErrorOut = components['schemas']['ReportErrorOut'];

export type PingOut = components['schemas']['PingOut'];
export type PingConference = components['schemas']['PingConference'];
export type TerminalSettings = components['schemas']['TerminalSettings'];
export type TerminalPrintJobOut = components['schemas']['TerminalPrintJobOut'];

export type ErrorOut = components['schemas']['ErrorOut'];

export type ImportReportOut = components['schemas']['ImportReportOut'];
export type ImportAcceptedOut = components['schemas']['ImportAcceptedOut'];

export type PrintJobOut = components['schemas']['PrintJobOut'];
export type PrintJobRefOut = components['schemas']['PrintJobRefOut'];

export type RoleOut = components['schemas']['RoleOut'];
export type RoleIn = components['schemas']['RoleIn'];
export type UserOut = components['schemas']['UserOut'];
export type UserCreateIn = components['schemas']['UserCreateIn'];
export type UserUpdateIn = components['schemas']['UserUpdateIn'];
export type PermissionOut = components['schemas']['PermissionOut'];

export type TerminalOut = components['schemas']['TerminalOut'];
export type TerminalIn = components['schemas']['TerminalIn'];
export type TerminalTokenOut = components['schemas']['TerminalTokenOut'];

export type PrinterAdminOut = components['schemas']['PrinterAdminOut'];
export type PrinterIn = components['schemas']['PrinterIn'];
export type PrinterOut = components['schemas']['PrinterOut'];
export type PrinterTokenOut = components['schemas']['PrinterTokenOut'];

export type ProfileActive = components['schemas']['ProfileActive'];
export type ProfileRevoked = components['schemas']['ProfileRevoked'];

export type EventOut = components['schemas']['EventOut'];

export type PageParticipantShort = components['schemas']['Page_ParticipantShort_'];
export type PageConferenceOut = components['schemas']['Page_ConferenceOut_'];
export type PageTemplateOut = components['schemas']['Page_TemplateOut_'];
export type PageRoleOut = components['schemas']['Page_RoleOut_'];
export type PageUserOut = components['schemas']['Page_UserOut_'];
export type PageTerminalOut = components['schemas']['Page_TerminalOut_'];
export type PagePrinterAdminOut = components['schemas']['Page_PrinterAdminOut_'];
export type PageImportBatchShort = components['schemas']['Page_ImportBatchShort_'];
export type PageEventOut = components['schemas']['Page_EventOut_'];
