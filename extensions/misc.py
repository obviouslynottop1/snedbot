import logging
import re
import typing as t
from difflib import get_close_matches

import hikari
import lightbulb
import miru
import psutil
import pytz

from etc import constants as const
from models import SnedBot
from models.checks import bot_has_permissions
from models.checks import has_permissions
from models.context import SnedMessageContext
from models.context import SnedSlashContext
from utils import helpers
from utils.scheduler import ConversionMode

logger = logging.getLogger(__name__)

misc = lightbulb.Plugin("Miscellaneous Commands")
psutil.cpu_percent(interval=1)  # Call so subsequent calls for CPU % will not be blocking

RGB_REGEX = re.compile(r"[0-9]{1,3} [0-9]{1,3} [0-9]{1,3}")


@misc.command
@lightbulb.command("ping", "Check the bot's latency.")
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: SnedSlashContext) -> None:
    embed = hikari.Embed(
        title="🏓 Pong!",
        description=f"Latency: `{round(ctx.app.heartbeat_latency * 1000)}ms`",
        color=const.MISC_COLOR,
    )
    await ctx.respond(embed=embed)


@misc.command
@lightbulb.option("detach", "Send the embed in a detached manner from the slash command.", type=bool, required=False)
@lightbulb.option(
    "color",
    "The color of the embed. Expects three space-separated values for an RGB value.",
    type=hikari.Color,
    required=False,
)
@lightbulb.option("author_url", "An URL to direct users to if the author is clicked.", required=False)
@lightbulb.option(
    "author_image_url",
    "An URL pointing to an image to use for the author's avatar.",
    required=False,
)
@lightbulb.option("author", "The author of the embed. Appears above the title.", required=False)
@lightbulb.option(
    "footer_image_url",
    "An url pointing to an image to use for the embed footer.",
    required=False,
)
@lightbulb.option(
    "image_url",
    "An url pointing to an image to use for the embed image.",
    required=False,
)
@lightbulb.option(
    "thumbnail_url",
    "An url pointing to an image to use for the thumbnail.",
    required=False,
)
@lightbulb.option("footer", "The footer of the embed.", required=False)
@lightbulb.option("description", "The description of the embed.", required=False)
@lightbulb.option("title", "The title of the embed. Required.")
@lightbulb.command("embed", "Generates a new embed with the parameters specified")
@lightbulb.implements(lightbulb.SlashCommand)
async def embed(ctx: SnedSlashContext) -> None:
    url_options = [
        ctx.options.image_url,
        ctx.options.thumbnail_url,
        ctx.options.footer_image_url,
        ctx.options.author_image_url,
        ctx.options.author_url,
    ]
    for option in url_options:
        if option and not helpers.is_url(option):
            embed = hikari.Embed(
                title="❌ Invalid URL",
                description=f"Provided an invalid URL.",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            return

    if ctx.options.color is not None and not RGB_REGEX.fullmatch(ctx.options.color):
        embed = hikari.Embed(
            title="❌ Invalid Color",
            description=f"Colors must be of format `RRR GGG BBB`, three values seperated by spaces.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = (
        hikari.Embed(
            title=ctx.options.title,
            description=ctx.options.description,
            color=ctx.options.color,
        )
        .set_footer(ctx.options.footer, icon=ctx.options.footer_image_url)
        .set_image(ctx.options.image_url)
        .set_thumbnail(ctx.options.thumbnail_url)
        .set_author(
            name=ctx.options.author,
            url=ctx.options.author_url,
            icon=ctx.options.author_image_url,
        )
    )

    if not ctx.options.detach:
        await ctx.respond(embed=embed)
        return

    if ctx.member and not helpers.includes_permissions(
        lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES
    ):
        embed = hikari.Embed(
            title="❌ Missing Permissions",
            description=f"Sending embeds detached requires `Manage Messages` permissions!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if ctx.guild_id:
        me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
        channel = ctx.get_channel()

        if not isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel)):
            embed = hikari.Embed(
                title="❌ Cannot send in thread.",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            return

        assert me is not None

        if not helpers.includes_permissions(
            lightbulb.utils.permissions_in(channel, me),
            hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL,
        ):
            raise lightbulb.BotMissingRequiredPermission(
                perms=hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
            )

    await ctx.app.rest.create_message(ctx.channel_id, embed=embed)
    embed = hikari.Embed(title="✅ Embed created!", color=const.EMBED_GREEN)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@embed.set_error_handler
async def embed_error(event: lightbulb.CommandErrorEvent) -> None:
    if isinstance(event.exception, lightbulb.CommandInvocationError) and isinstance(
        event.exception.original, ValueError
    ):
        embed = hikari.Embed(
            title="❌ Parsing error",
            description=f"An error occurred parsing parameters.\n**Error:** ```{event.exception.original}```",
            color=const.ERROR_COLOR,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return
    raise


@misc.command
@lightbulb.command("about", "Displays information about the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def about(ctx: SnedSlashContext) -> None:
    me = ctx.app.get_me()
    assert me is not None

    embed = hikari.Embed(
        title=f"ℹ️ About {me.username}",
        description=f"""**• Made by:** `Hyper#0001`
**• Servers:** `{len(ctx.app.cache.get_guilds_view())}`
**• Invite:** [Invite me!](https://discord.com/oauth2/authorize?client_id={me.id}&permissions=1494984682710&scope=bot%20applications.commands)
**• Support:** [Click here!](https://discord.gg/KNKr8FPmJa)
**• Terms of Service:** [Click here!](https://github.com/HyperGH/snedbot_v2/blob/main/tos.md)
**• Privacy Policy:** [Click here!](https://github.com/HyperGH/snedbot_v2/blob/main/privacy.md)\n
Blob emoji is licensed under [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)""",
        color=const.EMBED_BLUE,
    )
    embed.set_thumbnail(me.avatar_url)
    embed.add_field(
        name="CPU utilization",
        value=f"`{round(psutil.cpu_percent(interval=None))}%`",
        inline=True,
    )
    process = psutil.Process()  # gets current process
    embed.add_field(
        name="Memory utilization",
        value=f"`{round(process.memory_info().vms / 1048576)}MB`",
        inline=True,
    )
    embed.add_field(
        name="Latency",
        value=f"`{round(ctx.app.heartbeat_latency * 1000)}ms`",
        inline=True,
    )
    await ctx.respond(embed=embed)


@misc.command
@lightbulb.command("invite", "Invite the bot to your server!")
@lightbulb.implements(lightbulb.SlashCommand)
async def invite(ctx: SnedSlashContext) -> None:

    if not ctx.app.dev_mode:
        invite_url = f"https://discord.com/oauth2/authorize?client_id={ctx.app.user_id}&permissions=1494984682710&scope=applications.commands%20bot"
        embed = hikari.Embed(
            title="🌟 Yay!",
            description=f"[Click here]({invite_url}) for an invite link!",
            color=const.MISC_COLOR,
        )
        await ctx.respond(embed=embed)
    else:
        embed = hikari.Embed(
            title="🌟 Oops!",
            description=f"It looks like this bot is in developer mode, and not intended to be invited!",
            color=const.MISC_COLOR,
        )
        await ctx.respond(embed=embed)


@misc.command
@lightbulb.add_cooldown(10.0, 1, lightbulb.GuildBucket)
@lightbulb.add_checks(
    has_permissions(hikari.Permissions.MANAGE_NICKNAMES),
    bot_has_permissions(hikari.Permissions.CHANGE_NICKNAME),
)
@lightbulb.option("nickname", "The nickname to set the bot's nickname to. Type 'None' to reset it!")
@lightbulb.command("setnick", "Set the bot's nickname!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def setnick(ctx: SnedSlashContext, nickname: t.Optional[str] = None) -> None:
    assert ctx.guild_id is not None

    nickname = nickname[:32] if nickname and not nickname.casefold() == "none" else None

    await ctx.app.rest.edit_my_member(
        ctx.guild_id, nickname=nickname, reason=f"Nickname changed via /setnick by {ctx.author}"
    )
    embed = hikari.Embed(title="✅ Nickname changed!", color=const.EMBED_GREEN)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.command("support", "Provides a link to the support Discord.")
@lightbulb.implements(lightbulb.SlashCommand)
async def support(ctx: SnedSlashContext) -> None:
    await ctx.respond("https://discord.gg/KNKr8FPmJa", flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.command("source", "Provides a link to the source-code of the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def source(ctx: SnedSlashContext) -> None:
    await ctx.respond("<https://github.com/HyperGH/snedbot>")


@misc.command
@lightbulb.command("serverinfo", "Provides detailed information about this server.")
@lightbulb.implements(lightbulb.SlashCommand)
async def serverinfo(ctx: SnedSlashContext) -> None:
    assert ctx.guild_id is not None
    guild = ctx.app.cache.get_available_guild(ctx.guild_id)
    assert guild is not None

    embed = hikari.Embed(
        title=f"ℹ️ Server Information",
        description=f"""**• Name:** `{guild.name}`
**• ID:** `{guild.id}`
**• Owner:** `{ctx.app.cache.get_member(guild.id, guild.owner_id)}` (`{guild.owner_id}`)
**• Created at:** {helpers.format_dt(guild.created_at)} ({helpers.format_dt(guild.created_at, style="R")})
**• Member count:** `{guild.member_count}`
**• Roles:** `{len(guild.get_roles())}`
**• Channels:** `{len(guild.get_channels())}`
**• Nitro Boost level:** `{guild.premium_tier}`
**• Nitro Boost count:** `{guild.premium_subscription_count or '*Not found*'}`
**• Preferred locale:** `{guild.preferred_locale}`
**• Community:** `{"Yes" if "COMMUNITY" in guild.features else "No"}`
**• Partner:** `{"Yes" if "PARTNERED" in guild.features else "No"}`
**• Verified:** `{"Yes" if "VERIFIED" in guild.features else "No"}`
**• Discoverable:** `{"Yes" if "DISCOVERABLE" in guild.features else "No"}`
**• Monetization enabled:** `{"Yes" if "MONETIZATION_ENABLED" in guild.features else "No"}`
{f"**• Vanity URL:** {guild.vanity_url_code}" if guild.vanity_url_code else ""}
""",
        color=const.EMBED_BLUE,
    )

    embed.set_thumbnail(guild.icon_url)
    embed.set_image(guild.banner_url)

    await ctx.respond(embed=embed)


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.VIEW_CHANNEL),
    has_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option(
    "channel",
    "The channel to send the message to, defaults to the current channel.",
    required=False,
    type=hikari.TextableGuildChannel,
    channel_types=[hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS],
)
@lightbulb.option("text", "The text to echo.")
@lightbulb.command("echo", "Repeat the provided text as the bot.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def echo(ctx: SnedSlashContext, text: str, channel: t.Optional[hikari.InteractionChannel] = None) -> None:
    # InteractionChannel has no overrides data
    send_to = (ctx.app.cache.get_guild_channel(channel.id) or ctx.get_channel()) if channel else ctx.get_channel()

    assert ctx.guild_id is not None

    if not send_to:
        embed = hikari.Embed(title="❌ Cannot send message in threads yet!", color=const.ERROR_COLOR)
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert isinstance(send_to, hikari.TextableGuildChannel) and me is not None

    perms = lightbulb.utils.permissions_in(send_to, me)
    if not helpers.includes_permissions(perms, hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL
        )

    await send_to.send(text)

    embed = hikari.Embed(title="✅ Message sent!", color=const.EMBED_GREEN)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY, hikari.Permissions.VIEW_CHANNEL
    ),
    has_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option("message_link", "You can get this by right-clicking a message.", type=str)
@lightbulb.command("edit", "Edit a message that was sent by the bot.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def edit(ctx: SnedSlashContext, message_link: str) -> None:

    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    assert ctx.guild_id is not None

    channel = ctx.app.cache.get_guild_channel(message.channel_id) or await ctx.app.rest.fetch_channel(
        message.channel_id
    )

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)

    overwrites_channel = (
        channel
        if not isinstance(channel, hikari.GuildThreadChannel)
        else ctx.app.cache.get_guild_channel(channel.parent_id)
    )
    assert (
        isinstance(channel, (hikari.TextableGuildChannel))
        and me is not None
        and isinstance(overwrites_channel, hikari.GuildChannel)
    )

    perms = lightbulb.utils.permissions_in(overwrites_channel, me)
    if not helpers.includes_permissions(
        perms,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
    ):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY
        )

    if message.author.id != ctx.app.user_id:
        embed = hikari.Embed(
            title="❌ Not Authored",
            description="The bot did not author this message, thus it cannot edit it.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    modal = miru.Modal(f"Editing message in #{channel.name}")
    modal.add_item(
        miru.TextInput(
            label="Content",
            style=hikari.TextInputStyle.PARAGRAPH,
            placeholder="Type the new content for this message...",
            value=message.content,
            required=True,
            max_length=2000,
        )
    )
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    content = list(modal.values.values())[0]
    await message.edit(content=content)

    embed = hikari.Embed(title="✅ Message edited!", color=const.EMBED_GREEN)
    await modal.get_response_context().respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
    )
)
@lightbulb.command("Raw Content", "Show raw content for this message.", pass_options=True)
@lightbulb.implements(lightbulb.MessageCommand)
async def raw(ctx: SnedMessageContext, target: hikari.Message) -> None:
    if target.content:
        await ctx.respond(f"```{target.content}```", flags=hikari.MessageFlag.EPHEMERAL)
    else:
        embed = hikari.Embed(
            title="❌ Missing Content",
            description="Oops! It looks like this message has no content to display!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.option("timezone", "The timezone to set as your default. Example: 'Europe/Kiev'", autocomplete=True)
@lightbulb.command(
    "timezone", "Sets your preferred timezone for other time-related commands to use.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def set_timezone(ctx: SnedSlashContext, timezone: str) -> None:
    if timezone.title() not in pytz.common_timezones:
        embed = hikari.Embed(
            title="❌ Invalid Timezone",
            description="Oops! This does not look like a valid timezone! Specify your timezone as a valid `Continent/City` combination.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    await ctx.app.db.execute(
        """
    INSERT INTO preferences (user_id, timezone) 
    VALUES ($1, $2) 
    ON CONFLICT (user_id) DO 
    UPDATE SET timezone = $2""",
        ctx.user.id,
        timezone.title(),
    )
    await ctx.app.db_cache.refresh(table="preferences", user_id=ctx.user.id, timezone=timezone.title())

    embed = hikari.Embed(
        title="✅ Timezone set!",
        description=f"Your preferred timezone has been set to `{timezone.title()}`, all relevant commands will try to adapt to this setting! (E.g. `/reminder`)",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@set_timezone.autocomplete("timezone")
async def tz_opts(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        assert isinstance(option.value, str)
        return get_close_matches(option.value.title(), pytz.common_timezones, 25)
    return []


@misc.command
@lightbulb.option(
    "style",
    "Timestamp style.",
    choices=[
        "t - Short time",
        "T - Long time",
        "d - Short date",
        "D - Long Date",
        "f - Short Datetime",
        "F - Long Datetime",
        "R - Relative",
    ],
    required=False,
)
@lightbulb.option("time", "The time to create the timestamp from. Examples: 'in 20 minutes', '2022-04-03', '21:43'")
@lightbulb.command(
    "timestamp", "Create a Discord timestamp from human-readable time formats and dates.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def timestamp_gen(ctx: SnedSlashContext, time: str, style: t.Optional[str] = None) -> None:
    try:
        converted_time = await ctx.app.scheduler.convert_time(
            time, conversion_mode=ConversionMode.ABSOLUTE, user=ctx.user
        )
    except ValueError as error:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description=f"Your timeformat is invalid! \n**Error:** {error}",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return
    style = style.split(" -")[0] if style else "f"

    await ctx.respond(
        f"`{helpers.format_dt(converted_time, style=style)}` --> {helpers.format_dt(converted_time, style=style)}"
    )


def load(bot: SnedBot) -> None:
    bot.add_plugin(misc)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(misc)
