"""Каталог разрешений (AD-04). Коды хранятся в БД как текст, список — только здесь."""

from enum import StrEnum


class Permission(StrEnum):
    PARTICIPANTS_VIEW = "participants.view"
    REGISTRATION_DESK = "registration.desk"
    STICKERS_PRINT = "stickers.print"
    PARTICIPANTS_EDIT = "participants.edit"
    PARTICIPANTS_ADD = "participants.add"
    REGISTRATION_FOREIGN_CODE = "registration.foreign_code"
    IMPORTS_RUN = "imports.run"
    CONFERENCES_MANAGE = "conferences.manage"
    DEVICES_MANAGE = "devices.manage"
    USERS_MANAGE = "users.manage"


PERMISSION_TITLES: dict[Permission, str] = {
    Permission.PARTICIPANTS_VIEW: "Просмотр и поиск участников",
    Permission.REGISTRATION_DESK: "Регистрация со стойки, в том числе без наклейки",
    Permission.STICKERS_PRINT: "Печать и повторная печать наклеек",
    Permission.PARTICIPANTS_EDIT: "Исправление данных участника",
    Permission.PARTICIPANTS_ADD: "Добавление участника",
    Permission.REGISTRATION_FOREIGN_CODE: "Отметка «Зарегистрирован по чужому коду»",
    Permission.IMPORTS_RUN: "Загрузка участников",
    Permission.CONFERENCES_MANAGE: "Настройка конференций и шаблонов",
    Permission.DEVICES_MANAGE: "Настройка терминалов и принтеров",
    Permission.USERS_MANAGE: "Управление учётными записями и ролями",
}

REGISTRAR_ROLE = "Регистратор"
ADMIN_ROLE = "Администратор"

DEFAULT_ROLES: dict[str, set[Permission]] = {
    REGISTRAR_ROLE: {
        Permission.PARTICIPANTS_VIEW,
        Permission.REGISTRATION_DESK,
        Permission.STICKERS_PRINT,
        Permission.PARTICIPANTS_EDIT,
        Permission.PARTICIPANTS_ADD,
        Permission.REGISTRATION_FOREIGN_CODE,
    },
    ADMIN_ROLE: set(Permission),
}
