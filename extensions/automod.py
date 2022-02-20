import datetime
import enum
import json
import logging
import typing as t

import hikari
import re
import lightbulb
import miru
import perspective
from etc.settings_static import default_automod_policies, notices
from models.bot import SnedBot
from utils import helpers
import utils
from utils.ratelimiter import BucketType

logger = logging.getLogger(__name__)

automod = lightbulb.Plugin("Auto-Moderation", include_datastore=True)
automod.d.actions = lightbulb.utils.DataStore()


class AutomodActionType(enum.Enum):
    INVITES = "invites"
    SPAM = "spam"
    MASS_MENTIONS = "mass_mentions"
    ATTACH_SPAM = "attach_spam"
    LINK_SPAM = "link_spam"
    CAPS = "caps"
    BAD_WORDS = "bad_words"
    ESCALATE = "escalate"
    PERSPECTIVE = "perspective"


class AutoModState(enum.Enum):
    DISABLED = "disabled"
    FLAG = "flag"
    NOTICE = "notice"
    WARN = "warn"
    ESCALATE = "escalate"
    TIMEOUT = "timeout"
    KICK = "kick"
    SOFTBAN = "softban"
    TEMPBAN = "tempban"
    PERMABAN = "permaban"


spam_ratelimiter = utils.RateLimiter(10, 8, bucket=BucketType.MEMBER, wait=False)
punish_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
attach_spam_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
link_spam_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
escalate_prewarn_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
escalate_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)


async def get_policies(guild: hikari.SnowflakeishOr[hikari.Guild]) -> t.Dict[str, t.Any]:
    """Return auto-moderation policies for the specified guild."""

    guild_id = hikari.Snowflake(guild)

    records = await automod.app.db_cache.get(table="mod_config", guild_id=guild_id)

    policies = json.loads(records[0]["automod_policies"]) if records else default_automod_policies

    for key in default_automod_policies.keys():
        if key not in policies:
            policies[key] = default_automod_policies[key]

        for nested_key in default_automod_policies[key].keys():
            if nested_key not in policies[key]:
                policies[key][nested_key] = default_automod_policies[key][nested_key]

    invalid = []
    for key in policies.keys():
        if key not in default_automod_policies.keys():
            invalid.append(key)

    for key in invalid:
        policies.pop(key)

    return policies


automod.d.actions.get_policies = get_policies


async def punish(
    message: hikari.Message,
    policies: t.Dict[str, t.Any],
    action: AutomodActionType,
    reason: str,
    offender: t.Optional[hikari.Member] = None,
    original_action: t.Optional[AutomodActionType] = None,
) -> None:

    required_perms = (
        hikari.Permissions.BAN_MEMBERS
        | hikari.Permissions.MODERATE_MEMBERS
        | hikari.Permissions.MANAGE_MESSAGES
        | hikari.Permissions.KICK_MEMBERS
    )

    me = automod.app.cache.get_member(message.guild_id, automod.app.user_id)

    offender = offender or message.member

    if not helpers.can_harm(me, offender, permission=required_perms):
        return

    # Check if channel is excluded
    if not original_action and message.channel_id in policies[action.value]["excluded_channels"]:
        return

    # Check if member has excluded role
    role_ids = [role_id for role_id in message.member.role_ids if role_id in policies[action.value]["excluded_roles"]]
    if not original_action and role_ids:
        return

    state = policies[action.value]["state"]

    if state == AutoModState.DISABLED.value:
        return

    # States that silence the user and their repetition is undesirable
    silencers = [
        AutoModState.TIMEOUT.value,
        AutoModState.KICK.value,
        AutoModState.TEMPBAN.value,
        AutoModState.SOFTBAN.value,
        AutoModState.PERMABAN.value,
    ]

    if policies[AutoModState.ESCALATE.value]["state"] in silencers:
        silencers.append(AutoModState.ESCALATE.value)

    if state in silencers:
        await punish_ratelimiter.acquire(message)

        if punish_ratelimiter.is_rate_limited(message):
            return

    if not original_action:
        temp_dur = policies[action.value]["temp_dur"]
        should_delete = policies[action.value]["delete"] if action.value != "spam" else False

    else:
        temp_dur = policies[original_action.value]["temp_dur"]
        should_delete = False

    if should_delete:
        await helpers.maybe_delete(message)

    mod = automod.app.get_plugin("Moderation")

    if not mod:
        return

    if state == AutoModState.FLAG.value:
        await mod.d.actions.flag_user(
            offender.id, message.guild_id, message, reason=f"Message flagged by auto-moderator for {reason}."
        )

    if state == AutoModState.NOTICE.value:
        embed = hikari.Embed(
            title="💬 Auto-Moderation Notice",
            description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
            color=automod.app.warn_color,
        )
        await message.respond(content=offender.mention, embed=embed, user_mentions=True)
        await mod.d.actions.flag_user(
            offender.id, message.guild_id, message, reason=f"Message flagged by auto-moderator for {reason}."
        )

    if state == AutoModState.WARN.value:
        embed = await mod.d.actions.warn(offender, me, f"Warned by auto-moderator for {reason}.")
        return await message.respond(embed=embed)

    elif state == AutoModState.ESCALATE.value:
        await escalate_prewarn_ratelimiter.acquire(message)

        if not escalate_prewarn_ratelimiter.is_rate_limited(message):
            embed = hikari.Embed(
                title="💬 Auto-Moderation Notice",
                description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
                color=automod.app.warn_color,
            )
            await message.respond(content=offender.mention, embed=embed, user_mentions=True)
            return await mod.d.actions.flag_user(
                offender.id,
                message.guild_id,
                message,
                reason=f"Message flagged by auto-moderator for {reason} ({action.name}).",
            )

        elif escalate_prewarn_ratelimiter.is_rate_limited(message):
            embed = await mod.d.actions.warn(
                offender,
                me,
                f"Warned by auto-moderator for previous offenses ({action.name}).",
            )
            return await message.respond(embed=embed)

        else:
            await escalate_ratelimiter.acquire(message)
            if escalate_ratelimiter.is_rate_limited(message):
                return await punish(
                    message=message,
                    policies=policies,
                    action=AutomodActionType.ESCALATE,
                    reason=f"previous offenses ({action.name})",
                    original_action=action,
                    offender=offender,
                )

    elif state == AutoModState.TIMEOUT.value:

        embed = await mod.d.actions.timeout(
            offender,
            me,
            helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Timed out by auto-moderator for {reason}.",
        )
        return await message.respond(embed=embed)

    elif state == AutoModState.KICK.value:
        embed = await mod.d.actions.kick(offender, me, reason=f"Kicked by auto-moderator for {reason}.")
        return await message.respond(embed=embed)

    elif state == AutoModState.SOFTBAN.value:
        embed = await mod.d.actions.ban(
            offender, me, soft=True, reason=f"Soft-banned by auto-moderator for {reason}.", days_to_delete=1
        )
        return await message.respond(embed=embed)

    elif state == AutoModState.TEMPBAN.value:
        embed = await mod.d.actions.ban(
            offender,
            me,
            duration=helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Temp-banned by auto-moderator for {reason}.",
        )
        return await message.respond(embed=embed)

    elif state == AutoModState.PERMABAN.value:
        embed = await mod.d.actions.ban(offender, me, reason=f"Permanently banned by auto-moderator for {reason}.")
        return await message.respond(embed=embed)


@automod.listener(hikari.GuildMessageCreateEvent, bind=True)
@automod.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def scan_messages(
    plugin: lightbulb.Plugin, event: t.Union[hikari.GuildMessageCreateEvent, hikari.GuildMessageDeleteEvent]
) -> None:
    """Scan messages for all possible offences."""

    message = event.message

    if message.author is None:
        # Probably a partial update, ignore it
        return

    if not plugin.app.is_started or not plugin.app.db_cache.is_ready:
        return

    if message.guild_id is None:
        return

    if not message.member or message.member.is_bot:
        return

    policies = await get_policies(message.guild_id)

    if policies["mass_mentions"]["state"] != AutoModState.DISABLED.value:
        mentions = sum(user.id != message.author.id and not user.is_bot for user in message.mentions.users.values())

        if mentions >= policies["mass_mentions"]["count"]:
            return await punish(
                message,
                policies,
                AutomodActionType.MASS_MENTIONS,
                reason=f"spamming {mentions}/{policies['mass_mentions']['count']} mentions in a single message",
            )

    await spam_ratelimiter.acquire(message)
    if policies["spam"]["state"] != AutoModState.DISABLED.value and spam_ratelimiter.is_rate_limited(message):
        return await punish(message, policies, AutomodActionType.SPAM, reason="spam")

    if policies["attach_spam"]["state"] != AutoModState.DISABLED.value and message.attachments:
        await attach_spam_ratelimiter.acquire(message)

        if attach_spam_ratelimiter.is_rate_limited(message):
            await punish(
                message, policies, AutomodActionType.ATTACH_SPAM, reason="posting images/attachments too quickly"
            )

    # Everything that requires message content follows below
    if not message.content:
        return

    if policies["caps"]["state"] != AutoModState.DISABLED.value and len(message.content) > 15:
        chars = [char for char in message.content if char.isalnum()]
        uppers = [char for char in chars if char.isupper()]
        if len(uppers) / len(chars) > 0.6:
            return await punish(
                message,
                policies,
                AutomodActionType.CAPS,
                reason="use of excessive caps",
            )

    if policies["bad_words"]["state"] != AutoModState.DISABLED.value:
        for word in message.content.lower().split(" "):
            if word in policies["bad_words"]["words_list"]:
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words")

        for bad_word in policies["bad_words"]["words_list"]:
            if " " in bad_word and bad_word.lower() in message.content.lower():
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words (expression)")

        for bad_word in policies["bad_words"]["words_list_wildcard"]:
            if bad_word.lower() in message.content.lower():
                return await punish(
                    message, policies, AutomodActionType.BAD_WORDS, reason="usage of bad words (wildcard)"
                )

    if policies["invites"]["state"] != AutoModState.DISABLED.value:
        invite_regex = re.compile(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?")

        if invite_regex.findall(message.content):
            return await punish(
                message,
                policies,
                AutomodActionType.INVITES,
                reason="posting Discord invites",
            )

    if policies["link_spam"]["state"] != AutoModState.DISABLED.value:
        link_regex = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        link_matches = link_regex.findall(message.content)
        if len(link_matches) > 7:
            return await punish(
                message,
                policies,
                AutomodActionType.LINK_SPAM,
                reason="having too many links in a single message",
            )

        if link_matches:
            await link_spam_ratelimiter.acquire(message)

            if link_spam_ratelimiter.is_rate_limited(message):
                return await punish(
                    message,
                    policies,
                    AutomodActionType.LINK_SPAM,
                    reason="posting links too quickly",
                )

    if policies["perspective"]["state"] != AutoModState.DISABLED.value:
        persp_attribs = [
            perspective.Attribute(perspective.AttributeName.TOXICITY),
            perspective.Attribute(perspective.AttributeName.SEVERE_TOXICITY),
            perspective.Attribute(perspective.AttributeName.PROFANITY),
            perspective.Attribute(perspective.AttributeName.INSULT),
            perspective.Attribute(perspective.AttributeName.THREAT),
        ]
        try:
            resp: perspective.AnalysisResponse = await plugin.app.perspective.analyze(message.content, persp_attribs)
        except perspective.wrapper.PerspectiveException:
            return
        scores = {score.name.name: score.summary.value for score in resp.attribute_scores}

        for score, value in scores.items():
            if value > policies["perspective"]["persp_bounds"][score]:
                return await punish(
                    message,
                    policies,
                    AutomodActionType.PERSPECTIVE,
                    reason=f"toxic content detected by Perspective ({score.replace('_', ' ').lower()}: {round(value*100)}%)",
                )


def load(bot: SnedBot) -> None:
    bot.add_plugin(automod)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(automod)
