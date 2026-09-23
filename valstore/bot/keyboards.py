"""Inline keyboards.

Everything the user can do is a button. That is what makes the bot usable on a
phone by someone who will never type a command, and it needs no hosting — the
buttons ride the same long-polling connection as everything else.
"""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AccountCB(CallbackData, prefix="acc"):
    """Actions on one account. account_id is 0 where the action needs none."""

    action: str
    account_id: int = 0


class LinkCB(CallbackData, prefix="lnk"):
    """Pick a way to link."""

    method: str


def accounts_list(accounts, at_capacity: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for account in accounts:
        star = "⭐ " if account.is_default else ""
        builder.button(
            text=f"{star}{account.title}",
            callback_data=AccountCB(action="open", account_id=account.id),
        )
    if not at_capacity:
        builder.button(
            text="➕ Link another account",
            callback_data=AccountCB(action="add"),
        )
    builder.adjust(1)
    return builder.as_markup()


def no_accounts() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Link an account", callback_data=AccountCB(action="add"))
    return builder.as_markup()


def account_detail(account) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Store",
                   callback_data=AccountCB(action="store", account_id=account.id))
    builder.button(text="🎒 Skins",
                   callback_data=AccountCB(action="inv", account_id=account.id))
    builder.button(text="✏️ Rename",
                   callback_data=AccountCB(action="rename", account_id=account.id))
    if not account.is_default:
        builder.button(
            text="⭐ Make default",
            callback_data=AccountCB(action="default", account_id=account.id),
        )
    builder.button(text="🔄 Re-link",
                   callback_data=AccountCB(action="relink", account_id=account.id))
    builder.button(text="🗑 Remove",
                   callback_data=AccountCB(action="remove", account_id=account.id))
    builder.button(text="⬅️ All accounts", callback_data=AccountCB(action="list"))
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def confirm_remove(account) -> InlineKeyboardMarkup:
    """Removal is irreversible, so it never happens on a single tap."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Yes, remove it",
        callback_data=AccountCB(action="remove_confirm", account_id=account.id),
    )
    builder.button(
        text="Cancel",
        callback_data=AccountCB(action="open", account_id=account.id),
    )
    builder.adjust(1)
    return builder.as_markup()


def pick_account(accounts, action: str) -> InlineKeyboardMarkup:
    """Which account to run a command against."""
    builder = InlineKeyboardBuilder()
    for account in accounts:
        star = "⭐ " if account.is_default else ""
        builder.button(
            text=f"{star}{account.title}",
            callback_data=AccountCB(action=action, account_id=account.id),
        )
    builder.adjust(1)
    return builder.as_markup()


def link_methods(registry) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for method in registry:
        builder.button(text=method.title, callback_data=LinkCB(method=method.id))
    builder.button(text="Cancel", callback_data=AccountCB(action="list"))
    builder.adjust(1)
    return builder.as_markup()


def after_link(account) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Store",
                   callback_data=AccountCB(action="store", account_id=account.id))
    builder.button(text="🎒 Skins",
                   callback_data=AccountCB(action="inv", account_id=account.id))
    builder.button(text="👤 My accounts", callback_data=AccountCB(action="list"))
    builder.adjust(2, 1)
    return builder.as_markup()
