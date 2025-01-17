import asyncio
import logging

import hikari
import lightbulb

from etc import constants as const
from etc import get_perm_str
from models import SnedSlashContext
from models.bot import SnedBot

logger = logging.getLogger(__name__)

troubleshooter = lightbulb.Plugin("Troubleshooter")

# Find perms issues
# Find automod config issues
# Find missing channel perms issues
# ...

REQUIRED_PERMISSIONS = (
    hikari.Permissions.VIEW_AUDIT_LOG
    | hikari.Permissions.MANAGE_ROLES
    | hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
    | hikari.Permissions.MANAGE_CHANNELS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.CHANGE_NICKNAME
    | hikari.Permissions.READ_MESSAGE_HISTORY
    | hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.CREATE_PUBLIC_THREADS
    | hikari.Permissions.CREATE_PRIVATE_THREADS
    | hikari.Permissions.SEND_MESSAGES_IN_THREADS
    | hikari.Permissions.EMBED_LINKS
    | hikari.Permissions.ATTACH_FILES
    | hikari.Permissions.MENTION_ROLES
    | hikari.Permissions.USE_EXTERNAL_EMOJIS
    | hikari.Permissions.MODERATE_MEMBERS
    | hikari.Permissions.MANAGE_MESSAGES
    | hikari.Permissions.ADD_REACTIONS
)

# Explain why the bot requires the perm
PERM_DESCRIPTIONS = {
    hikari.Permissions.VIEW_AUDIT_LOG: "Required in logs to fill in details such as who the moderator in question was, or the reason of the action.",
    hikari.Permissions.MANAGE_ROLES: "Required to give users roles via role-buttons.",
    hikari.Permissions.MANAGE_CHANNELS: "Used by `/slowmode` to set a custom slow mode duration for the channel.",
    hikari.Permissions.MANAGE_THREADS: "Used by `/slowmode` to set a custom slow mode duration for the thread.",
    hikari.Permissions.KICK_MEMBERS: "Required to use the `/kick` command and let auto-moderation actions kick users.",
    hikari.Permissions.BAN_MEMBERS: "Required to use the `/ban`, `/softban`, `/massban` command and let auto-moderation actions ban users.",
    hikari.Permissions.CHANGE_NICKNAME: "Required for the `/setnick` command.",
    hikari.Permissions.READ_MESSAGE_HISTORY: "Required for auto-moderation, starboard, `/edit`, and other commands that may require to fetch messages.",
    hikari.Permissions.VIEW_CHANNEL: "Required for auto-moderation, starboard, `/edit`, and other commands that may require to fetch messages.",
    hikari.Permissions.SEND_MESSAGES: "Required to send messages independently of commands, this includes `/echo`, `/edit`, logging, starboard, reports and auto-moderation.",
    hikari.Permissions.CREATE_PUBLIC_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.CREATE_PRIVATE_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.SEND_MESSAGES_IN_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.EMBED_LINKS: "Required for the bot to create embeds to display content, without this you may not see any responses from the bot, including this one :)",
    hikari.Permissions.ATTACH_FILES: "Required for the bot to attach files to a message, for example to send a list of users to be banned in `/massban`.",
    hikari.Permissions.MENTION_ROLES: "Required for the bot to always be able to mention roles, for example when reporting users. The bot will **never** mention @everyone or @here.",
    hikari.Permissions.USE_EXTERNAL_EMOJIS: "Required to display certain content with custom emojies, typically to better illustrate certain content.",
    hikari.Permissions.ADD_REACTIONS: "This permission is used for creating giveaways and adding the initial reaction to the giveaway message.",
    hikari.Permissions.MODERATE_MEMBERS: "Required to use the `/timeout` command and let auto-moderation actions timeout users.",
    hikari.Permissions.MANAGE_MESSAGES: "This permission is required to delete other user's messages, for example in the case of auto-moderation.",
}


@troubleshooter.command
@lightbulb.command("troubleshoot", "Diagnose and locate common configuration issues.")
@lightbulb.implements(lightbulb.SlashCommand)
async def troubleshoot(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me is not None

    perms = lightbulb.utils.permissions_for(me)
    missing_perms = ~perms & REQUIRED_PERMISSIONS
    content = []

    if missing_perms is not hikari.Permissions.NONE:
        content.append("**Missing Permissions:**")
        content += [
            f"❌ **{get_perm_str(perm)}**: {desc}" for perm, desc in PERM_DESCRIPTIONS.items() if missing_perms & perm
        ]

    if not content:
        embed = hikari.Embed(
            title="✅ No problems found!",
            description="If you believe there is an issue with Sned, found a bug, or simply have a question, please join the [support server!](https://discord.gg/KNKr8FPmJa)",
            color=const.EMBED_GREEN,
        )
    else:
        content = "\n".join(content)
        embed = hikari.Embed(
            title="Uh Oh!",
            description=f"It looks like there may be some issues with the configuration. Please review the list below!\n\n{content}\n\nIf you need any assistance resolving these issues, please join the [support server!](https://discord.gg/KNKr8FPmJa)",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


def load(bot: SnedBot) -> None:
    bot.add_plugin(troubleshooter)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(troubleshooter)
