"""Telegram handlers.

Handlers stay thin on purpose: they resolve who is asking, delegate to a
service, and turn whatever comes back — including failures — into a sentence.
No Riot logic and no SQL lives here.
"""

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from valstore.bot import keyboards as kb
from valstore.bot import texts
from valstore.bot.keyboards import AccountCB, LinkCB
from valstore.errors import (
    AccountLimitReached,
    AccountNotFound,
    AssetUnavailable,
    CloudflareBlock,
    LinkError,
    RateLimited,
    ReauthError,
    SessionDecryptError,
    ValstoreError,
)

log = logging.getLogger("valstore.bot.handlers")

router = Router()


class LinkFlow(StatesGroup):
    waiting_for_session = State()


class RenameFlow(StatesGroup):
    waiting_for_name = State()


# ---- shared helpers ----

def _uid(event) -> int | None:
    """Telegram id of whoever sent this, or None.

    from_user is genuinely optional on the Message type (channel posts), so it
    is checked rather than assumed.
    """
    user = getattr(event, "from_user", None)
    return user.id if user else None


def explain(exc: Exception) -> str:
    """A failure as something the user can act on.

    CloudflareBlock is tested before ReauthError because it is a subclass, and
    the two need different advice.
    """
    if isinstance(exc, RateLimited):
        minutes = max(1, exc.retry_after_seconds // 60)
        return texts.ERR_RATE_LIMITED.format(minutes=minutes)
    if isinstance(exc, SessionDecryptError):
        return texts.ERR_SESSION_UNREADABLE
    if isinstance(exc, CloudflareBlock):
        return texts.ERR_CLOUDFLARE
    if isinstance(exc, ReauthError):
        return texts.ERR_SESSION_EXPIRED
    if isinstance(exc, AssetUnavailable):
        return texts.ERR_CATALOG
    if isinstance(exc, AccountNotFound):
        return texts.ERR_NO_SUCH_ACCOUNT
    if isinstance(exc, AccountLimitReached):
        return str(exc)
    if isinstance(exc, LinkError):
        return str(exc)
    return texts.ERR_UNEXPECTED


def accounts_panel(accounts_service, telegram_id):
    """(text, keyboard) for the account list — the bot's home screen."""
    accounts = accounts_service.list_accounts(telegram_id)
    if not accounts:
        return texts.NO_ACCOUNTS, kb.no_accounts()
    header = texts.ACCOUNTS_HEADER.format(count=len(accounts))
    return header, kb.accounts_list(
        accounts, at_capacity=accounts_service.at_capacity(telegram_id)
    )


def detail_panel(account):
    text = texts.ACCOUNT_DETAIL.format(
        title=account.title,
        shard=account.shard.upper(),
        default_note=texts.DEFAULT_NOTE if account.is_default else "",
    )
    return text, kb.account_detail(account)


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    """Replace the panel in place, tolerating Telegram's 'not modified' error."""
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception as exc:  # message unchanged, too old, or deleted
        log.debug("edit_text failed (%s); sending instead", type(exc).__name__)
        try:
            await callback.message.answer(text, reply_markup=markup)
        except Exception:
            log.warning("could not deliver panel to %s", _uid(callback))


async def _run_command(message: Message, account, command, executor) -> None:
    """Run one AccountCommand and send its messages."""
    busy = None
    try:
        busy = await message.answer(command.busy_text)
    except Exception:
        log.debug("could not send busy notice")

    try:
        chunks = await executor.execute(account, command)
    except ValstoreError as exc:
        await message.answer(explain(exc))
        return
    except Exception:
        log.exception("command %s failed for account %s",
                      type(command).__name__, account.id)
        await message.answer(texts.ERR_UNEXPECTED)
        return
    finally:
        if busy is not None:
            try:
                await busy.delete()
            except Exception:
                pass  # a stale busy notice is cosmetic, never worth failing on

    # Plain text on purpose: skin names are arbitrary and would break Markdown.
    for chunk in chunks:
        await message.answer(chunk)


async def _dispatch_command(message: Message, telegram_id, accounts, executor,
                            command, action: str) -> None:
    """Resolve which account to act on, asking only when it is ambiguous."""
    linked = accounts.list_accounts(telegram_id)
    if not linked:
        await message.answer(texts.NO_ACCOUNTS, reply_markup=kb.no_accounts())
        return
    if len(linked) == 1:
        await _run_command(message, linked[0], command, executor)
        return
    await message.answer("Which account?",
                         reply_markup=kb.pick_account(linked, action))


async def _begin_link(send, telegram_id, registry, guard, state) -> None:
    """Offer the link methods, skipping the menu when there is only one."""
    if not guard.enabled:
        await send(texts.LINKING_DISABLED)
        return
    if len(registry) == 0:
        await send(texts.LINKING_DISABLED)
        return

    only = registry.only
    if only is None:
        await send(texts.CHOOSE_LINK_METHOD, reply_markup=kb.link_methods(registry))
        return

    challenge = only.start(telegram_id)
    await state.set_state(LinkFlow.waiting_for_session)
    await state.update_data(method=only.id)
    await send(challenge.instructions)


async def _finish_link(message: Message, telegram_id, response, accounts,
                       registry, guard, state) -> None:
    """Validate a link response and store the account."""
    data = await state.get_data()
    method = registry.get(data.get("method", ""))
    if method is None:
        await state.clear()
        await message.answer(texts.ERR_UNEXPECTED)
        return

    try:
        guard.check(telegram_id)
    except RateLimited as exc:
        await state.clear()
        await message.answer(explain(exc))
        return

    await message.answer(texts.LINK_VALIDATING)
    guard.record(telegram_id)

    try:
        result = await asyncio.to_thread(method.complete, telegram_id, response)
    except ValstoreError as exc:
        # Stay in the flow: a retry should not need the menu again.
        await message.answer(explain(exc))
        return
    except Exception:
        log.exception("link method %s crashed", method.id)
        await message.answer(texts.ERR_UNEXPECTED)
        return

    try:
        account, relinked = accounts.link(telegram_id, result)
    except AccountLimitReached as exc:
        await state.clear()
        await message.answer(explain(exc))
        return
    await state.clear()

    template = texts.LINK_REFRESHED if relinked else texts.LINK_SUCCESS
    await message.answer(
        template.format(title=account.title, shard=account.shard.upper()),
        reply_markup=kb.after_link(account),
    )
    if method.post_link_note:
        await message.answer(method.post_link_note)


# ---- commands ----

@router.message(CommandStart())
async def cmd_start(message: Message, accounts):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    await message.answer(texts.WELCOME)
    text, markup = accounts_panel(accounts, telegram_id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(texts.HELP)


@router.message(Command("accounts"))
async def cmd_accounts(message: Message, accounts):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    text, markup = accounts_panel(accounts, telegram_id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.LINK_CANCELLED)


@router.message(Command("store"))
async def cmd_store(message: Message, accounts, executor, store_command):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    await _dispatch_command(message, telegram_id, accounts, executor,
                            store_command, "store")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, accounts, executor, inventory_command):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    await _dispatch_command(message, telegram_id, accounts, executor,
                            inventory_command, "inv")


@router.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject, accounts, registry,
                   guard, state: FSMContext):
    """Kept for anyone still sending the old one-shot `/link <blob>`."""
    telegram_id = _uid(message)
    if telegram_id is None:
        return

    blob = (command.args or "").strip()
    if not blob:
        await _begin_link(message.answer, telegram_id, registry, guard, state)
        return

    sealed = registry.get("sealed")
    if sealed is None:
        await _begin_link(message.answer, telegram_id, registry, guard, state)
        return
    await state.set_state(LinkFlow.waiting_for_session)
    await state.update_data(method=sealed.id)
    await _finish_link(message, telegram_id, blob, accounts, registry, guard, state)


# ---- owner-only levers (not an allowlist: everyone else still gets the bot) ----

@router.message(Command("lockdown"))
async def cmd_lockdown(message: Message, guard, cfg):
    telegram_id = _uid(message)
    if cfg.owner_id is None or telegram_id != cfg.owner_id:
        return
    guard.enabled = False
    await message.answer("🔒 Linking is paused. /unlock re-enables it.")


@router.message(Command("unlock"))
async def cmd_unlock(message: Message, guard, cfg):
    telegram_id = _uid(message)
    if cfg.owner_id is None or telegram_id != cfg.owner_id:
        return
    guard.enabled = True
    await message.answer("🔓 Linking is enabled again.")


# ---- callbacks ----

@router.callback_query(AccountCB.filter(F.action == "list"))
async def cb_list(callback: CallbackQuery, accounts, state: FSMContext):
    telegram_id = _uid(callback)
    if telegram_id is None:
        await callback.answer()
        return
    await state.clear()
    text, markup = accounts_panel(accounts, telegram_id)
    await _edit(callback, text, markup)
    await callback.answer()


@router.callback_query(AccountCB.filter(F.action == "open"))
async def cb_open(callback: CallbackQuery, callback_data: AccountCB, accounts):
    telegram_id = _uid(callback)
    if telegram_id is None:
        await callback.answer()
        return
    try:
        account = accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    text, markup = detail_panel(account)
    await _edit(callback, text, markup)
    await callback.answer()


@router.callback_query(AccountCB.filter(F.action == "add"))
async def cb_add(callback: CallbackQuery, accounts, registry, guard,
                 state: FSMContext):
    telegram_id = _uid(callback)
    if telegram_id is None or callback.message is None:
        await callback.answer()
        return
    if accounts.at_capacity(telegram_id):
        await callback.answer(
            texts.AT_CAPACITY.format(max=accounts.max_per_user), show_alert=True
        )
        return
    await callback.answer()
    await _begin_link(callback.message.answer, telegram_id, registry, guard, state)


@router.callback_query(LinkCB.filter())
async def cb_pick_method(callback: CallbackQuery, callback_data: LinkCB, registry,
                         guard, state: FSMContext):
    telegram_id = _uid(callback)
    if telegram_id is None or callback.message is None:
        await callback.answer()
        return
    method = registry.get(callback_data.method)
    if method is None or not guard.enabled:
        await callback.answer(texts.LINKING_DISABLED, show_alert=True)
        return
    await callback.answer()
    challenge = method.start(telegram_id)
    await state.set_state(LinkFlow.waiting_for_session)
    await state.update_data(method=method.id)
    await callback.message.answer(challenge.instructions)


@router.callback_query(AccountCB.filter(F.action.in_({"store", "inv"})))
async def cb_run(callback: CallbackQuery, callback_data: AccountCB, accounts,
                 executor, store_command, inventory_command):
    telegram_id = _uid(callback)
    if telegram_id is None or callback.message is None:
        await callback.answer()
        return
    try:
        account = accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    await callback.answer()
    command = store_command if callback_data.action == "store" else inventory_command
    await _run_command(callback.message, account, command, executor)


@router.callback_query(AccountCB.filter(F.action == "default"))
async def cb_default(callback: CallbackQuery, callback_data: AccountCB, accounts):
    telegram_id = _uid(callback)
    if telegram_id is None:
        await callback.answer()
        return
    if not accounts.set_default(callback_data.account_id, telegram_id):
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    account = accounts.require(callback_data.account_id, telegram_id)
    await callback.answer(texts.DEFAULT_SET.format(title=account.title))
    text, markup = detail_panel(account)
    await _edit(callback, text, markup)


@router.callback_query(AccountCB.filter(F.action == "remove"))
async def cb_remove(callback: CallbackQuery, callback_data: AccountCB, accounts):
    telegram_id = _uid(callback)
    if telegram_id is None:
        await callback.answer()
        return
    try:
        account = accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    await _edit(callback, texts.CONFIRM_REMOVE.format(title=account.title),
                kb.confirm_remove(account))
    await callback.answer()


@router.callback_query(AccountCB.filter(F.action == "remove_confirm"))
async def cb_remove_confirm(callback: CallbackQuery, callback_data: AccountCB,
                            accounts):
    telegram_id = _uid(callback)
    if telegram_id is None:
        await callback.answer()
        return
    try:
        account = accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return

    title = account.title
    accounts.remove(account.id, telegram_id)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.REMOVED.format(title=title))
    text, markup = accounts_panel(accounts, telegram_id)
    await _edit(callback, text, markup)


@router.callback_query(AccountCB.filter(F.action == "relink"))
async def cb_relink(callback: CallbackQuery, callback_data: AccountCB, accounts,
                    registry, guard, state: FSMContext):
    """Refresh an expired session without removing the account first."""
    telegram_id = _uid(callback)
    if telegram_id is None or callback.message is None:
        await callback.answer()
        return
    try:
        accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    await callback.answer()
    await _begin_link(callback.message.answer, telegram_id, registry, guard, state)


@router.callback_query(AccountCB.filter(F.action == "rename"))
async def cb_rename(callback: CallbackQuery, callback_data: AccountCB, accounts,
                    state: FSMContext):
    telegram_id = _uid(callback)
    if telegram_id is None or callback.message is None:
        await callback.answer()
        return
    try:
        account = accounts.require(callback_data.account_id, telegram_id)
    except AccountNotFound:
        await callback.answer(texts.ERR_NO_SUCH_ACCOUNT, show_alert=True)
        return
    await state.set_state(RenameFlow.waiting_for_name)
    await state.update_data(account_id=account.id)
    await callback.answer()
    await callback.message.answer(texts.RENAME_PROMPT.format(title=account.title))


# ---- stateful replies ----

@router.message(StateFilter(RenameFlow.waiting_for_name), F.text)
async def on_rename_reply(message: Message, accounts, state: FSMContext):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    data = await state.get_data()
    account_id = data.get("account_id")
    await state.clear()

    if account_id is None:
        await message.answer(texts.ERR_UNEXPECTED)
        return
    if not accounts.rename(account_id, telegram_id, message.text or ""):
        await message.answer(texts.RENAME_EMPTY)
        return

    account = accounts.require(account_id, telegram_id)
    await message.answer(texts.RENAMED.format(label=account.label))
    text, markup = detail_panel(account)
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(LinkFlow.waiting_for_session), F.text)
async def on_link_reply(message: Message, accounts, registry, guard,
                        state: FSMContext):
    telegram_id = _uid(message)
    if telegram_id is None:
        return
    await _finish_link(message, telegram_id, message.text or "", accounts,
                       registry, guard, state)
