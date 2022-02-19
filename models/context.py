from __future__ import annotations

import miru
import lightbulb
import hikari
import typing as t
from .views import AuthorOnlyView
from utils import helpers
import functools

__all__ = ["SnedContext", "SnedSlashContext", "SnedMessageContext", "SnedUserContext", "SnedPrefixContext"]

if t.TYPE_CHECKING:
    from .bot import SnedBot


class ConfirmView(AuthorOnlyView):
    """View that drives the confirm prompt button logic."""

    def __init__(
        self,
        lctx: lightbulb.Context,
        timeout: int,
        confirm_resp: t.Optional[t.Dict[str, t.Any]] = None,
        cancel_resp: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> None:
        super().__init__(lctx, timeout=timeout)
        self.confirm_resp = confirm_resp
        self.cancel_resp = cancel_resp
        self.value: t.Optional[bool] = None

    @miru.button(label="Confirm", emoji="✔️", style=hikari.ButtonStyle.SUCCESS)
    async def confirm_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        self.value = True
        if self.confirm_resp:
            await ctx.respond(**self.confirm_resp)
        self.stop()

    @miru.button(label="Cancel", emoji="✖️", style=hikari.ButtonStyle.DANGER)
    async def confirm_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        self.value = False
        if self.cancel_resp:
            await ctx.respond(**self.cancel_resp)
        self.stop()


class SnedContext(lightbulb.Context):
    async def confirm(
        self,
        *args,
        confirm_payload: t.Optional[t.Dict[str, t.Any]] = None,
        cancel_payload: t.Optional[t.Dict[str, t.Any]] = None,
        timeout: int = 120,
        message: t.Optional[hikari.Message] = None,
        **kwargs,
    ) -> bool:
        """Confirm a given action.

        Parameters
        ----------
        confirm_payload : Optional[Dict[str, Any]], optional
            Optional keyword-only payload to send if the user confirmed, by default None
        cancel_payload : Optional[Dict[str, Any]], optional
            Optional keyword-only payload to send if the user cancelled, by default None
        message : Optional[hikari.Message], optional
            A message to edit & transform into the confirm prompt if provided, by default None
        *args : Any
            Arguments for the confirm prompt response.
        **kwargs : Any
            Keyword-only arguments for the confirm prompt response.

        Returns
        -------
        bool
            Boolean determining if the user confirmed the action or not.
            None if no response was given before timeout.
        """

        view = ConfirmView(self, timeout, confirm_payload, cancel_payload)

        if message:
            message = await message.edit(*args, **kwargs)
        else:
            resp = await self.respond(*args, **kwargs)
            message = helpers.resolve_response(resp)

        view.start(message)
        await view.wait()
        return view.value

    @t.overload
    async def mod_respond(
        self,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> t.Union[lightbulb.ResponseProxy, hikari.Message]:
        ...

    @t.overload
    async def mod_respond(
        self,
        response_type: hikari.ResponseType,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> t.Union[lightbulb.ResponseProxy, hikari.Message]:
        ...

    async def mod_respond(self, *args, **kwargs) -> t.Union[lightbulb.ResponseProxy, hikari.Message]:
        """Respond to the command while taking into consideration the current moderation command settings.
        This should not be used outside the moderation plugin, and may fail if it is not loaded."""
        mod = self.app.get_plugin("Moderation")

        if mod:
            is_ephemeral = (await self.app.get_plugin("Moderation").d.actions.get_settings(self.guild_id))[
                "is_ephemeral"
            ]
            flags = hikari.MessageFlag.EPHEMERAL if is_ephemeral else hikari.MessageFlag.NONE

        await self.respond(*args, flags=flags, **kwargs)

    @property
    def app(self) -> SnedBot:
        return super().app

    @property
    def bot(self) -> SnedBot:
        return super().bot


class SnedSlashContext(SnedContext, lightbulb.SlashContext):
    """Custom SlashContext for Sned."""


class SnedUserContext(SnedContext, lightbulb.UserContext):
    """Custom UserContext for Sned."""


class SnedMessageContext(SnedContext, lightbulb.MessageContext):
    """Custom MessageContext for Sned."""


class SnedPrefixContext(SnedContext, lightbulb.PrefixContext):
    """Custom PrefixContext for Sned."""